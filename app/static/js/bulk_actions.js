class CampaignBulkController {
  constructor() {
    this.selectedIds = new Set();
    this.isProcessing = false;
    this.init();
  }

  init() {
    this.cacheElements();
    this.bindEvents();
    this.updateUI();
  }

  cacheElements() {
    this.table = document.getElementById('campTable');
    this.selectAllChk = document.getElementById('selectAllChk');
    this.bulkToolbar = document.getElementById('bulkToolbar');
    this.bulkCount = document.getElementById('bulkCount');
    this.actionButtons = document.querySelectorAll('.btn-bulk, .btn-bulk-icon');
  }

  getVisibleRows() {
    return Array.from(document.querySelectorAll('.camp-chk-row')).filter(
      chk => chk.closest('tr').style.display !== 'none'
    );
  }

  bindEvents() {
    if (!this.table) return;

    // Delegate row checkbox clicks
    this.table.addEventListener('change', (e) => {
      if (e.target.classList.contains('camp-chk-row')) {
        const id = e.target.value;
        if (e.target.checked) {
          this.selectedIds.add(id);
        } else {
          this.selectedIds.delete(id);
        }
        this.updateUI();
      }
    });

    if (this.selectAllChk) {
      this.selectAllChk.addEventListener('change', (e) => {
        const checked = e.target.checked;
        this.getVisibleRows().forEach(chk => {
          chk.checked = checked;
          if (checked) {
            this.selectedIds.add(chk.value);
          } else {
            this.selectedIds.delete(chk.value);
          }
        });
        this.updateUI();
      });
    }

    this.actionButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        if (this.isProcessing) return;
        const action = btn.dataset.action;
        
        if (action === 'clear') {
          this.clearSelection();
          return;
        }

        if (action === 'delete') {
          // Handled by global document click listener
          return;
        }
        
        if (action === 'assign') {
          new bootstrap.Modal(document.getElementById('assignScriptModal')).show();
          return;
        }
        
        if (action === 'move') {
          document.getElementById('moveCampaignCount').textContent = this.selectedIds.size;
          new bootstrap.Modal(document.getElementById('moveCampaignModal')).show();
          return;
        }

        this.performBulkAction(action);
      });
    });


    document.getElementById('btnConfirmAssignScript')?.addEventListener('click', () => {
      bootstrap.Modal.getInstance(document.getElementById('assignScriptModal'))?.hide();
      const scriptId = document.getElementById('bulkScriptSelect').value;
      this.performBulkAction('assign', { script_id: scriptId });
    });
    
    document.getElementById('btnConfirmMove')?.addEventListener('click', () => {
      bootstrap.Modal.getInstance(document.getElementById('moveCampaignModal'))?.hide();
      const groupId = document.getElementById('bulkGroupSelect').value;
      this.performBulkAction('move', { group_id: groupId });
    });
  }

  clearSelection() {
    this.selectedIds.clear();
    document.querySelectorAll('.camp-chk-row').forEach(chk => chk.checked = false);
    if (this.selectAllChk) this.selectAllChk.checked = false;
    this.updateUI();
  }

  updateUI() {
    const count = this.selectedIds.size;
    if (count > 0) {
      if (this.bulkCount) this.bulkCount.textContent = `✓ ${count} Selected`;
      if (this.bulkToolbar) this.bulkToolbar.style.display = 'block';
    } else {
      if (this.bulkToolbar) this.bulkToolbar.style.display = 'none';
      if (this.selectAllChk) this.selectAllChk.checked = false;
    }
    
    // Highlight rows
    document.querySelectorAll('.camp-chk-row').forEach(chk => {
      const row = chk.closest('tr');
      if (this.selectedIds.has(chk.value)) {
        row.classList.add('selected');
        chk.checked = true;
      } else {
        row.classList.remove('selected');
        chk.checked = false;
      }
    });
  }

  setProcessing(processing) {
    this.isProcessing = processing;
    this.actionButtons.forEach(btn => {
      btn.disabled = processing;
      if (processing) {
        btn.classList.add('processing');
        if (btn.tagName === 'BUTTON') {
            const originalHTML = btn.innerHTML;
            btn.dataset.originalHtml = originalHTML;
            btn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>`;
        }
      } else {
        btn.classList.remove('processing');
        if (btn.tagName === 'BUTTON' && btn.dataset.originalHtml) {
            btn.innerHTML = btn.dataset.originalHtml;
        }
      }
    });
  }

  async performBulkAction(action, extraData = {}) {
    if (this.selectedIds.size === 0) return;
    const ids = Array.from(this.selectedIds);
    this.setProcessing(true);

    try {
      const response = await fetch('/worker/api/campaigns/bulk-action', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': window.CSRF_TOKEN || ''
        },
        body: JSON.stringify({ action, ids, extra_data: extraData })
      });
      const data = await response.json();
      console.log(`[BULK ACTION] ${action} performed on ${ids.length} campaigns. Extra data:`, extraData);
      console.log("[BULK ACTION RESPONSE]", data);

      
      if (response.ok && data.success) {
        this.showToast("Success", data.message || `Bulk ${action} successful`, "success");
        setTimeout(() => {
          window.location.reload();
        }, 1000);
      } else {
        this.showToast("Error", data.error || data.message || "Failed to perform action", "danger");
      }
    } catch (e) {
      console.error("Bulk action failed", e);
      this.showToast("Error", "Network or server error during bulk action", "danger");
    } finally {
      this.setProcessing(false);
      this.clearSelection();
      this.cleanupUI();
    }
  }



  cleanupUI() {
    console.log("CLEANUP COMPLETE");

    // Hide modal safely:
    const activeModal = document.querySelector(".modal.show");
    if (activeModal) {
      const instance = bootstrap.Modal.getInstance(activeModal);
      if (instance) instance.hide();
    }

    // Hide modals if open
    ['deleteCampaignModal', 'assignScriptModal', 'moveCampaignModal'].forEach(id => {
      const modalEl = document.getElementById(id);
      if (modalEl) {
        const modalInstance = bootstrap.Modal.getInstance(modalEl);
        if (modalInstance) {
          modalInstance.hide();
        }
      }
    });

    // Always cleanup UI
    document.body.classList.remove("modal-open");
    document.body.style.removeProperty("overflow");
    document.body.style.removeProperty("padding-right");
    
    document.querySelectorAll(".modal-backdrop").forEach(x=>x.remove());
    document.querySelectorAll(".fade.show").forEach(x=>{
      if(x.classList.contains("modal-backdrop")) x.remove();
    });

    // Remove stuck loading
    document.body.classList.remove("loading");

    // Restore buttons
    document.querySelectorAll(".btn-bulk").forEach(b=>b.disabled=false);

    // Always run cleanup: hideLoader()
    if (typeof hideLoader === 'function') {
      hideLoader();
    }

    console.log("BACKDROP REMOVED");
  }

  showToast(title, message, type) {
    let container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
      container.style.zIndex = '1055';
      document.body.appendChild(container);
    }

    const toastEl = document.createElement('div');
    toastEl.className = `toast align-items-center text-white bg-${type} border-0`;
    toastEl.setAttribute('role', 'alert');
    toastEl.setAttribute('aria-live', 'assertive');
    toastEl.setAttribute('aria-atomic', 'true');
    toastEl.innerHTML = `
      <div class="d-flex">
        <div class="toast-body">
          <strong>${title}</strong>: ${message}
        </div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
      </div>
    `;
    container.appendChild(toastEl);
    
    const toast = new bootstrap.Toast(toastEl, { delay: 3000 });
    toast.show();
    toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
  }
}

document.addEventListener('DOMContentLoaded', () => {
  window.campaignBulkController = new CampaignBulkController();
});

// Explicit Global Delete Listener
document.addEventListener("click", async function(e) {
  const btn = e.target.closest('[data-action="delete"]');
  if (!btn) return;

  e.preventDefault();
  e.stopPropagation();

  const selected = [...document.querySelectorAll('.camp-chk-row:checked')];

  if (!selected.length) {
    alert("Select campaign");
    return;
  }

  if (!confirm("Delete selected campaigns?")) return;

  btn.disabled = true;

  try {
    const ids = selected.map(x => x.value);

    const res = await fetch("/worker/campaigns/bulk-delete", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": window.CSRF_TOKEN || ''
      },
      body: JSON.stringify({ campaign_ids: ids })
    });

    const data = await res.json();

    if (!res.ok) throw new Error(data.message || "Delete failed");

    selected.forEach(cb => {
      cb.closest("tr, .camp-row")?.remove();
    });
    
    // Clear the class state as well
    if (window.campaignBulkController) {
      window.campaignBulkController.clearSelection();
    }

  } catch (err) {
    console.error(err);
    alert(err.message);
  } finally {
    document.body.classList.remove("modal-open");
    document.body.style.overflow = "auto";
    document.body.style.paddingRight = "0";

    document.querySelectorAll(".modal-backdrop").forEach(x => x.remove());

    btn.disabled = false;
  }
});
