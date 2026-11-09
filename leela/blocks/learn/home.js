(() => {
  const abh = document.querySelector('.abh');
  if (!abh) return;
  if (!abh.dataset.dontGet) {
    abh.dataset.dontGet = '1';
    abh.addEventListener('click', e => {
      const b = e.target.closest('button.rh-page');
      if (!b) return;
      e.preventDefault(); e.stopImmediatePropagation();
      window.leeLearnToAgent?.(`I don't get this idea: ${abh.querySelector('#concept-name')?.textContent || b.dataset.t}`, true);
    }, true);
  }
})();
