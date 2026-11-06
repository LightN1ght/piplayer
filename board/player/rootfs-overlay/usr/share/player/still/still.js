(() => {
  'use strict';
  const picture = document.getElementById('picture');
  picture.addEventListener('error', () => { picture.src = '/placeholder.svg'; }, { once: true });
  async function poll() {
    try {
      const response = await fetch('/status.json', { cache: 'no-store', signal: AbortSignal.timeout(4000) });
      if (response.headers.get('X-PiPlayer-Mode') === 'video') window.location.replace('/');
    } catch (_) { /* Keep the still image during a temporary disconnect. */ }
    finally { window.setTimeout(poll, 2000); }
  }
  poll();
})();
