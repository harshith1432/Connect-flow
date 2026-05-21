document.addEventListener('DOMContentLoaded', function () {
  const typeSelect   = document.getElementById('campaignTypeSelect');
  const scriptSelect = document.getElementById('scriptSelect');
  const senderSelect = document.getElementById('senderNumberSelect');

  if (typeSelect && scriptSelect) {
    const allScriptOptions = Array.from(scriptSelect.options).slice(1);
    const allSenderOptions = senderSelect ? Array.from(senderSelect.options).slice(1) : [];

    typeSelect.addEventListener('change', function () {
      const selectedType = this.value;
      scriptSelect.innerHTML = '<option value="">— Choose Script —</option>';
      allScriptOptions.forEach(opt => {
        if (opt.dataset.type === selectedType) scriptSelect.appendChild(opt.cloneNode(true));
      });
      if (senderSelect) {
        senderSelect.innerHTML = '<option value="">— Use Platform Default —</option>';
        allSenderOptions.forEach(opt => {
          const ch = opt.dataset.channel;
          if (selectedType === 'call' && ['voice','hooman_voice'].includes(ch))
            senderSelect.appendChild(opt.cloneNode(true));
          else if (selectedType.startsWith('whatsapp') && ch === 'whatsapp')
            senderSelect.appendChild(opt.cloneNode(true));
        });
      }
    });
    typeSelect.dispatchEvent(new Event('change'));
  }

  // Voice preview
  const previewBtn = document.getElementById('btnPreviewCampaignScript');
  const audioPlayer = new Audio();
  if (previewBtn) {
    previewBtn.addEventListener('click', async function () {
      const sel = scriptSelect.options[scriptSelect.selectedIndex];
      if (!sel || !sel.value) { alert('Please select a script first.'); return; }
      const orig = this.innerHTML;
      this.disabled = true;
      this.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
      try {
        const res = await fetch('/worker/preview-voice', {
          method: 'POST',
          headers: {'Content-Type':'application/json','X-CSRFToken': window.CSRF_TOKEN},
          body: JSON.stringify({ text: sel.dataset.content, language: sel.dataset.lang })
        });
        const data = await res.json();
        if (data.success) { audioPlayer.src = data.audio_url; audioPlayer.play(); }
        else alert('Error: ' + data.error);
      } catch(e) { alert('Preview failed.'); }
      finally { this.disabled = false; this.innerHTML = orig; }
    });
  }

  // Filter table
  const search = document.getElementById('campSearch');
  const statusF = document.getElementById('statusFilter');
  const typeF   = document.getElementById('typeFilter');
  function filterTable() {
    const q = search.value.toLowerCase();
    const s = statusF.value;
    const t = typeF.value;
    document.querySelectorAll('#campTable tbody tr.camp-row').forEach(row => {
      const nameMatch   = row.dataset.name.includes(q);
      const statusMatch = !s || row.dataset.status === s;
      const typeMatch   = !t || row.dataset.type === t;
      row.style.display = (nameMatch && statusMatch && typeMatch) ? '' : 'none';
      
      // Keep checkbox state synchronized if hidden?
      // Actually we handle hiding in bulk_actions.js
    });
    
    // Update toolbar selection count based on visible rows
    // Dispatch an event to allow bulk_actions to update
    document.dispatchEvent(new CustomEvent('campTableFiltered'));
  }
  if (search)  search.addEventListener('input', filterTable);
  if (statusF) statusF.addEventListener('change', filterTable);
  if (typeF)   typeF.addEventListener('change', filterTable);
});
