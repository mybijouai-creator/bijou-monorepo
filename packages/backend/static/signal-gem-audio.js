/* =============================================================================
   Bijou AI — Signal Gem · Audio & State Controller
   v1.0 · 2026-07-25
   -----------------------------------------------------------------------------
   A small, dependency-free module that:

     • Plays the four brand cues (intro / tick / notify / engage)
     • Toggles the Signal Gem's chat state (idle / listening / speaking / thinking)
     • Handles Web Audio API autoplay restrictions (waits for first interaction)
     • Respects a global mute toggle (data-bj-audio="on|off" on <body>)
     • Falls back to HTMLAudioElement on legacy browsers

   Public API (window.BjAudio)
   -----------------------------------------------------------------------------
     BjAudio.play('intro' | 'tick' | 'notify' | 'engage' | 'mute-toggle')
     BjAudio.setState('idle' | 'listening' | 'speaking' | 'thinking')
     BjAudio.tick()              // shorthand for play('tick'), volume-aware
     BjAudio.unlock()            // manually unlock the AudioContext
     BjAudio.mute(on?: boolean)  // toggle / set mute
     BjAudio.state               // current gem state

   Filesystem layout expected
   -----------------------------------------------------------------------------
     /audio-identity/
       bj-intro.mp3
       bj-tick.mp3
       bj-notify.mp3
       bj-engage.mp3

   The file paths can be overridden with window.BJ_AUDIO_BASE before this script
   runs, e.g. `<script>window.BJ_AUDIO_BASE = '/assets/audio/';</script>`.

   Integration skeleton
   -----------------------------------------------------------------------------
     <link rel="stylesheet" href="signal-gem-states.css" />
     <script src="signal-gem-audio.js" defer></script>
     <body data-bj-audio="on">
       <div class="bj-gem bj-intro" data-bj-state="idle">
         <div class="gem-stage"> ...inline Signal Gem SVG... </div>
       </div>
     </body>
   ============================================================================= */
(function (root) {
  'use strict';

  // ---------------------------------------------------------------------------
  // Config
  // ---------------------------------------------------------------------------
  var DEFAULTS = {
    base:        (root.BJ_AUDIO_BASE || 'audio-identity/'),
    // Volume levels (Apple product-sound discipline: ambient = quiet, alert = louder)
    volumes: {
      intro:  0.45,   // logo reveal — subtle but present
      tick:   0.18,   // per-word — must NOT be annoying on long messages
      notify: 0.70,   // new message — needs to be heard
      engage: 0.55,   // voice mode toggle — present, warm
    },
    // Tick windowing: only fire a tick if the previous one was > this many ms ago.
    // Prevents the sound from clobbering itself if the bot streams words fast.
    tickMinGapMs:    110,
    // How much of the source MP3 to use for a single tick. The generated music
    // track is longer than we need; we sample just the first ~320ms.
    // (See integration-spec.md for why this number was chosen.)
    tickSourceMs:    320,
    // Fade-in / fade-out for ambient cues to avoid click artifacts.
    fadeInMs:        30,
    fadeOutMs:       80,
  };

  var VALID_STATES  = ['idle', 'listening', 'speaking', 'thinking'];
  var VALID_CUES    = ['intro', 'tick', 'notify', 'engage', 'mute-toggle'];

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  var audioCtx       = null;        // AudioContext, created on first user gesture
  var buffers        = {};          // {intro: AudioBuffer, tick: AudioBuffer, ...}
  var buffersReady   = false;       // true after decodeAudioData finishes
  var decodedUrls    = {};          // {intro: objectURL, ...} for HTMLAudioElement fallback
  var unlocked       = false;       // true once user gesture happened
  var lastTickAt     = 0;           // performance.now() of last tick play
  var currentState   = 'idle';
  var muted          = false;
  var introPlayed    = false;       // don't re-play intro on every state change

  // Pending cues queued before unlock — played as soon as user interacts.
  var pendingCues    = [];

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------
  function readMute() {
    var attr = document.body && document.body.getAttribute('data-bj-audio');
    if (attr === 'off' || attr === 'mute' || attr === 'muted') { return true; }
    return false;
  }

  function writeMute(on) {
    if (!document.body) { return; }
    document.body.setAttribute('data-bj-audio', on ? 'on' : 'off');
  }

  function resolveUrl(name) {
    return DEFAULTS.base + 'bj-' + name + '.mp3';
  }

  function isMuted() { return muted || readMute(); }

  // ---------------------------------------------------------------------------
  // Web Audio context — created lazily on first user gesture (autoplay policy)
  // ---------------------------------------------------------------------------
  function ensureContext() {
    if (audioCtx) { return audioCtx; }
    try {
      var Ctor = root.AudioContext || root.webkitAudioContext;
      if (!Ctor) { return null; }
      audioCtx = new Ctor();
    } catch (e) {
      audioCtx = null;
    }
    return audioCtx;
  }

  function unlock() {
    if (unlocked) { return; }
    var ctx = ensureContext();
    if (!ctx) { return; }
    if (ctx.state === 'suspended') {
      ctx.resume().catch(function () { /* user hasn't gestured yet */ });
    }
    unlocked = (ctx.state === 'running');
    if (unlocked) {
      // Pre-decode all cues into AudioBuffers for instant playback.
      decodeAll();
      // Drain any cues that were queued before unlock.
      flushPending();
    }
  }

  function decodeAll() {
    if (buffersReady) { return; }
    var ctx = ensureContext();
    if (!ctx) { return; }
    var fetches = Object.keys(DEFAULTS.volumes)
      .filter(function (k) { return k !== 'mute-toggle'; })
      .map(function (name) {
        return fetch(resolveUrl(name), { credentials: 'omit', cache: 'force-cache' })
          .then(function (r) { return r.arrayBuffer(); })
          .then(function (buf) { return ctx.decodeAudioData(buf); })
          .then(function (audioBuf) { buffers[name] = audioBuf; })
          .catch(function () { /* fall back to HTMLAudioElement at play-time */ });
      });
    Promise.all(fetches).then(function () { buffersReady = true; });
  }

  // ---------------------------------------------------------------------------
  // Playback — Web Audio path (preferred) and HTMLAudio fallback
  // ---------------------------------------------------------------------------
  function playWithWebAudio(name, opts) {
    opts = opts || {};
    var ctx = ensureContext();
    if (!ctx || !buffers[name]) { return false; }

    var src   = ctx.createBufferSource();
    src.buffer = buffers[name];

    // Tick: play only the first `tickSourceMs` of the source.
    var duration = (name === 'tick')
      ? Math.min(DEFAULTS.tickSourceMs / 1000, src.buffer.duration)
      : src.buffer.duration;

    var gain = ctx.createGain();
    var vol  = (opts.volume != null) ? opts.volume : DEFAULTS.volumes[name];
    var now  = ctx.currentTime;
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(Math.max(0.0001, vol), now + DEFAULTS.fadeInMs / 1000);
    gain.gain.setValueAtTime(Math.max(0.0001, vol), now + Math.max(DEFAULTS.fadeInMs, duration * 1000 - DEFAULTS.fadeOutMs) / 1000);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);

    src.connect(gain).connect(ctx.destination);
    src.start(now, 0, duration);
    return true;
  }

  function playWithHtmlAudio(name, opts) {
    opts = opts || {};
    if (!decodedUrls[name]) {
      decodedUrls[name] = resolveUrl(name);
    }
    try {
      var el = new Audio();
      el.src = decodedUrls[name];
      el.volume = (opts.volume != null) ? opts.volume : DEFAULTS.volumes[name];
      el.preload = 'auto';
      // For tick: we can't sample a sub-clip with HTMLAudio cleanly, so play
      // full file. The integration spec recommends keeping tick.mp3 short.
      el.play().catch(function () { /* user hasn't interacted yet */ });
      return true;
    } catch (e) { return false; }
  }

  function play(name, opts) {
    if (isMuted()) { return false; }
    if (VALID_CUES.indexOf(name) === -1) { return false; }

    // Tick: enforce minimum gap to avoid clipping on fast streams.
    if (name === 'tick') {
      var now = performance.now();
      if (now - lastTickAt < DEFAULTS.tickMinGapMs) { return false; }
      lastTickAt = now;
    }

    if (!unlocked) {
      // Queue and try to unlock on this gesture (in case it's a click handler).
      pendingCues.push({ name: name, opts: opts });
      unlock();
      return false;
    }

    var ok = playWithWebAudio(name, opts);
    if (!ok) { ok = playWithHtmlAudio(name, opts); }
    return ok;
  }

  function flushPending() {
    var queue = pendingCues.slice();
    pendingCues = [];
    queue.forEach(function (c) { play(c.name, c.opts); });
  }

  // ---------------------------------------------------------------------------
  // State management
  // ---------------------------------------------------------------------------
  function setState(next) {
    if (VALID_STATES.indexOf(next) === -1) { return; }
    if (next === currentState) { return; }
    var prev = currentState;
    currentState = next;

    // Find every gem container and update both class + data-attr.
    var gems = document.querySelectorAll('.bj-gem');
    Array.prototype.forEach.call(gems, function (el) {
      VALID_STATES.forEach(function (s) { el.classList.remove('state-' + s); });
      el.classList.add('state-' + next);
      el.setAttribute('data-bj-state', next);
    });

    // Auto-play the voice engage cue on first transition into listening.
    if (next === 'listening' && prev !== 'listening' && !introPlayed) {
      // First-time listen: pair the engage cue with the intro reveal.
      play('engage');
      introPlayed = true;
    }
  }

  function tick() { play('tick'); }

  function mute(on) {
    if (typeof on === 'boolean') {
      muted = on;
    } else {
      muted = !muted;
    }
    writeMute(muted);
    if (muted) { play('mute-toggle'); /* no actual file, used as a hook */ }
  }

  // ---------------------------------------------------------------------------
  // Auto-bind: detect data-bj-state changes elsewhere in the app
  // ---------------------------------------------------------------------------
  function watchStateAttribute() {
    var targets = document.querySelectorAll('[data-bj-state]');
    Array.prototype.forEach.call(targets, function (el) {
      new MutationObserver(function (mutations) {
        mutations.forEach(function (m) {
          var v = el.getAttribute('data-bj-state');
          if (v && v !== currentState) { setState(v); }
        });
      }).observe(el, { attributes: true, attributeFilter: ['data-bj-state'] });
    });
  }

  // ---------------------------------------------------------------------------
  // Page-load: play intro once, kick off the intro animation
  // ---------------------------------------------------------------------------
  function onFirstPaint() {
    // Add the bj-intro class so the logo-reveal animation runs.
    var gems = document.querySelectorAll('.bj-gem');
    Array.prototype.forEach.call(gems, function (el) { el.classList.add('bj-intro'); });
    setTimeout(function () {
      Array.prototype.forEach.call(gems, function (el) { el.classList.remove('bj-intro'); });
    }, 4600);

    // Try to play the intro cue. If audio isn't unlocked yet, this queues it.
    play('intro');
  }

  // ---------------------------------------------------------------------------
  // Wire up: mute attribute + user-gesture unlock + body class sync
  // ---------------------------------------------------------------------------
  function syncMuteFromBody() { muted = readMute(); }

  function bindUnlockEvents() {
    var events = ['pointerdown', 'keydown', 'touchstart', 'click'];
    var once = function () {
      unlock();
      events.forEach(function (e) { document.removeEventListener(e, once, true); });
    };
    events.forEach(function (e) { document.addEventListener(e, once, true); });
  }

  function init() {
    syncMuteFromBody();
    bindUnlockEvents();

    // Watch for external mute toggles (someone sets data-bj-audio="off" in DevTools).
    if (document.body) {
      new MutationObserver(syncMuteFromBody).observe(document.body, {
        attributes: true, attributeFilter: ['data-bj-audio'],
      });
    }

    // First-paint: start the intro animation and try the intro cue.
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () {
        watchStateAttribute();
        onFirstPaint();
      }, { once: true });
    } else {
      watchStateAttribute();
      onFirstPaint();
    }
  }

  // ---------------------------------------------------------------------------
  // Expose
  // ---------------------------------------------------------------------------
  root.BjAudio = {
    play:     play,
    tick:     tick,
    setState: setState,
    unlock:   unlock,
    mute:     mute,
    get state()     { return currentState; },
    get muted()     { return muted; },
    get isReady()   { return buffersReady; },
  };

  // Boot.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
}(typeof window !== 'undefined' ? window : this));
