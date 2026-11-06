/* All player assets are local: this page works without Internet access. */
(() => {
  'use strict';
  const video = document.getElementById('video');
  const screen = document.getElementById('screen');
  const message = document.getElementById('message');
  const start = document.getElementById('start');
  let hls = null;
  let generation = '';
  let soundRequested = false;
  let reconnectAt = 0;
  const say = text => { message.textContent = text; message.hidden = !text; };

  function disconnect() {
    if (hls) hls.destroy();
    hls = null;
    video.removeAttribute('src');
    video.load();
    generation = '';
  }
  async function play() {
    try {
      await video.play();
      if (!video.muted) soundRequested = true;
      start.hidden = soundRequested;
    } catch (_) {
      soundRequested = false;
      start.hidden = false;
      say('Нажмите «Смотреть», чтобы начать');
    }
  }
  function connect(id) {
    disconnect();
    generation = id;
    const url = `/hls/${encodeURIComponent(id)}/index.m3u8`;
    if (window.Hls && Hls.isSupported()) {
      console.debug('PiPlayer playback engine: hls.js');
      hls = new Hls({ maxBufferLength: 12, backBufferLength: 6 });
      hls.loadSource(url);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, play);
      hls.on(Hls.Events.ERROR, (_, data) => {
        if (data.fatal) {
          console.warn('PiPlayer stream error:', data.type, data.details);
          reconnectAt = Date.now() + 3000;
          disconnect();
          say('Восстановление потока…');
        }
      });
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      console.debug('PiPlayer playback engine: native HLS');
      video.src = url;
      play();
    } else {
      say('Этот браузер не поддерживает HLS. Откройте страницу в современном браузере.');
    }
  }
  function fullscreen() {
    if (screen.requestFullscreen) return screen.requestFullscreen().catch(() => {});
    if (video.webkitEnterFullscreen) video.webkitEnterFullscreen();
  }
  start.addEventListener('click', () => {
    video.muted = false;
    play();
    fullscreen();
  });
  document.getElementById('fullscreen').addEventListener('click', fullscreen);
  video.addEventListener('playing', () => say(''));
  video.addEventListener('waiting', () => say('Загрузка видео…'));
  video.addEventListener('error', () => { reconnectAt = Date.now() + 3000; disconnect(); });

  async function poll() {
    try {
      const response = await fetch('/status.json', { cache: 'no-store', signal: AbortSignal.timeout(4000) });
      if (!response.ok) throw new Error('status');
      const status = await response.json();
      if (status.state === 'playing') {
        if (status.generation !== generation && Date.now() >= reconnectAt) connect(status.generation);
        start.hidden = soundRequested;
      } else {
        if (generation) disconnect();
        start.hidden = true;
        if (status.state === 'waiting') say(status.error === 'unsupported_media' ? 'Файл не поддерживается. Нужен MP4 / H.264 / AAC.' : 'Загрузите видео через SFTP');
        else if (status.state === 'buffering') say('Подготовка трансляции…');
        else say(status.error === 'unsupported_media' ? 'Файл не поддерживается. Нужен MP4 / H.264 / AAC.' : 'Восстановление трансляции…');
      }
    } catch (_) { say('Нет связи с устройством. Повторное подключение…'); }
    finally { window.setTimeout(poll, 2000); }
  }
  poll();
})();
