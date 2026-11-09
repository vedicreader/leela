(() => {
  if (window.leeAbhVault) return;
  window.leeAbhVault = 1;
  document.addEventListener('click', e => {
    const a = e.target.closest?.('.abh a[href^="/v/"]'), m = a && /^\/v\/([^/?#]+)\/([^/?#]+)/.exec(a.getAttribute('href'));
    if (!m || !window.leeOpenVaultDoc) return;
    e.preventDefault(); e.stopImmediatePropagation();
    window.leeOpenVaultDoc(decodeURIComponent(m[2]), m[1] === 'store' ? '' : m[1], 'learn', a.dataset.title || '');
  }, true);
})();
