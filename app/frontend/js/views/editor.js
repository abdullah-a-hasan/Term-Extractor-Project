// View 3: Term Editor – load, review, confirm, export terminology

const Editor = {
    // State
    termsData: {},          // Raw {key: termObj} from JSON
    termsList: [],          // Processed array with added state
    filteredList: [],       // Current filtered view
    deletedTerms: [],       // Recycle bin
    fileMetadata: { unique_id: null, src_lang: null, tar_lang: null },

    currentPage: 1,
    perPage: 50,
    currentFilter: 'all',
    sourceFilter: '',
    targetFilter: '',
    useRegex: false,

    _currentCandKey: null,  // Key of term whose candidates modal is open
    _autoSaveTimer: null,
    _loaded: false,

    init() {
        this._bindToolbarEvents();
        this._bindPaginationEvents();
        this._bindModalEvents();

        // Open JSON from within editor toolbar
        DOM.on('btn-load-json-editor', 'click', async () => {
            const path = await API.browseJsonFile();
            if (path) await this.loadFromPath(path);
        });
    },

    // ==================== Loading ====================

    async loadFromLastResult() {
        try {
            const path = await API.getLastResultPath();
            if (path) await this.loadFromPath(path);
        } catch (e) {
            console.error('loadFromLastResult error:', e);
        }
    },

    async loadFromPath(path) {
        this._showLoading(true);
        try {
            const result = await API.loadTermsJson(path);
            if (!result.success) {
                DOM.showToast('Failed to load: ' + result.error, 'error');
                this._showLoading(false);
                return;
            }
            await this._processJsonData(result.data);
            this._showLoading(false);
        } catch (e) {
            DOM.showToast('Error loading file: ' + e.message, 'error');
            this._showLoading(false);
        }
    },

    async _processJsonData(jsonData) {
        // Support both {terms, unique_id, ...} and flat {key: termObj} structures
        if (jsonData.terms && jsonData.unique_id) {
            this.fileMetadata.unique_id = jsonData.unique_id;
            this.fileMetadata.src_lang = jsonData.src_lang || null;
            this.fileMetadata.tar_lang = jsonData.tar_lang || null;
            this.termsData = jsonData.terms;
        } else {
            this.fileMetadata.unique_id = null;
            this.fileMetadata.src_lang = null;
            this.fileMetadata.tar_lang = null;
            this.termsData = jsonData;
        }

        this.deletedTerms = [];
        this.currentPage = 1;
        this.currentFilter = 'all';
        this.sourceFilter = '';
        this.targetFilter = '';

        // Try to restore session
        let sessionMeta = {};
        let sessionDeleted = [];
        if (this.fileMetadata.unique_id) {
            try {
                const sess = await API.loadSession(this.fileMetadata.unique_id);
                if (sess.success && sess.data) {
                    sessionMeta = sess.data.metadata || {};
                    sessionDeleted = sess.data.deletedTerms || [];
                    DOM.showToast('📂 Restored previous session', 'info');
                }
            } catch (e) {
                console.error('Session load error:', e);
            }
        }

        // Remove deleted terms from termsData
        sessionDeleted.forEach(d => {
            if (this.termsData[d.key]) delete this.termsData[d.key];
        });
        this.deletedTerms = sessionDeleted;

        // Build termsList with session metadata
        this._buildTermsList(sessionMeta);
        this._applyFilters();
        this._renderTable();
        this._updateStats();
        this._updateRecycleCount();

        this._loaded = true;
        DOM.show('editor-content');
        DOM.setText('recycle-count', this.deletedTerms.length);
    },

    _buildTermsList(sessionMeta = {}) {
        this.termsList = Object.keys(this.termsData).map(key => {
            const data = this.termsData[key];
            const meta = sessionMeta[key] || {};
            const topCand = this._getTopCandidate(data.cands);

            return {
                key,
                source: data.original || key,
                target: meta.selectedTarget || (topCand ? topCand.term : ''),
                originalTarget: topCand ? topCand.term : '',
                count: data.count || 0,
                hits: topCand ? topCand.hits : 0,
                cands: data.cands || {},
                data,
                edited: meta.edited || false,
                confirmed: meta.confirmed || false,
                deleted: false,
            };
        });
    },

    // ==================== Filtering ====================

    _applyFilters() {
        let list = this.termsList;

        if (this.currentFilter === 'edited') list = list.filter(t => t.edited);
        else if (this.currentFilter === 'unedited') list = list.filter(t => !t.edited);
        else if (this.currentFilter === 'confirmed') list = list.filter(t => t.confirmed);
        else if (this.currentFilter === 'unconfirmed') list = list.filter(t => !t.confirmed);

        if (this.sourceFilter) {
            list = list.filter(t => this._matchesFilter(t.source, this.sourceFilter));
        }
        if (this.targetFilter) {
            list = list.filter(t => this._matchesFilter(t.target || t.originalTarget, this.targetFilter));
        }

        this.filteredList = list;
    },

    _matchesFilter(text, pattern) {
        if (!pattern) return true;
        try {
            if (this.useRegex) return new RegExp(pattern, 'i').test(text || '');
        } catch (e) { /* fall through */ }
        return (text || '').toLowerCase().includes(pattern.toLowerCase());
    },

    // ==================== Rendering ====================

    _renderTable() {
        const tbody = DOM.el('terms-tbody');
        if (!tbody) return;

        const total = this.filteredList.length;
        const totalPages = Math.max(1, Math.ceil(total / this.perPage));
        if (this.currentPage > totalPages) this.currentPage = totalPages;

        const start = (this.currentPage - 1) * this.perPage;
        const pageItems = this.filteredList.slice(start, start + this.perPage);

        if (pageItems.length === 0) {
            tbody.innerHTML = '<tr class="no-data-row"><td colspan="5">No terms to display</td></tr>';
        } else {
            tbody.innerHTML = '';
            pageItems.forEach((term, idx) => {
                const globalIdx = start + idx + 1;
                tbody.appendChild(this._renderRow(term, globalIdx));
            });
        }

        this._updatePagination(total, totalPages);
    },

    _renderRow(term, rowNum) {
        const tr = document.createElement('tr');
        tr.dataset.key = term.key;

        if (term.confirmed) tr.classList.add('row-confirmed');
        else if (term.edited) tr.classList.add('row-edited');

        // # column
        const tdNum = document.createElement('td');
        tdNum.className = 'col-num';
        tdNum.textContent = rowNum;

        // Source column
        const tdSrc = document.createElement('td');
        tdSrc.className = 'col-source';
        const srcInput = document.createElement('input');
        srcInput.type = 'text';
        srcInput.className = 'term-input';
        srcInput.value = term.source;
        srcInput.dir = 'auto';
        srcInput.readOnly = true;
        tdSrc.appendChild(srcInput);

        // Target column
        const tdTar = document.createElement('td');
        tdTar.className = 'col-target';
        const tarInput = document.createElement('input');
        tarInput.type = 'text';
        tarInput.className = 'term-input' + (term.edited ? ' edited' : '') + (term.confirmed ? ' confirmed' : '');
        tarInput.value = term.target || '';
        tarInput.dir = 'auto';
        tarInput.addEventListener('change', (e) => this._handleTargetEdit(term.key, e.target.value));
        tarInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                this._confirmTerm(term.key, true);
                this._focusNext(term.key);
            }
        });
        tdTar.appendChild(tarInput);

        // Count column
        const tdCount = document.createElement('td');
        tdCount.className = 'col-count';
        tdCount.innerHTML = `<span class="term-count">${term.count}</span>`;

        // Actions column
        const tdActions = document.createElement('td');
        tdActions.className = 'col-actions';
        const actions = document.createElement('div');
        actions.className = 'row-actions';

        const candCount = Object.keys(term.cands || {}).length;
        const btnCands = document.createElement('button');
        btnCands.className = 'btn-cands';
        btnCands.textContent = `📋 ${candCount}`;
        btnCands.title = `${candCount} candidate(s)`;
        btnCands.addEventListener('click', () => this._openCandidatesModal(term.key));

        const btnConfirm = document.createElement('button');
        btnConfirm.className = 'btn-confirm' + (term.confirmed ? ' confirmed' : '');
        btnConfirm.textContent = '✓';
        btnConfirm.title = term.confirmed ? 'Confirmed – click to un-confirm' : 'Confirm';
        btnConfirm.addEventListener('click', () => this._confirmTerm(term.key));

        const btnDel = document.createElement('button');
        btnDel.className = 'btn-delete';
        btnDel.textContent = '✗';
        btnDel.title = 'Delete (move to recycle bin)';
        btnDel.addEventListener('click', () => this._deleteTerm(term.key));

        actions.appendChild(btnCands);
        actions.appendChild(btnConfirm);
        actions.appendChild(btnDel);
        tdActions.appendChild(actions);

        tr.appendChild(tdNum);
        tr.appendChild(tdSrc);
        tr.appendChild(tdTar);
        tr.appendChild(tdCount);
        tr.appendChild(tdActions);

        return tr;
    },

    _updatePagination(total, totalPages) {
        const info = DOM.el('pagination-info');
        if (info) info.textContent = `Page ${this.currentPage} of ${totalPages} (${total} terms)`;

        const prevBtn = DOM.el('btn-prev-page');
        const nextBtn = DOM.el('btn-next-page');
        if (prevBtn) prevBtn.disabled = this.currentPage <= 1;
        if (nextBtn) nextBtn.disabled = this.currentPage >= totalPages;
    },

    _updateStats() {
        const total = this.termsList.length + this.deletedTerms.length;
        const active = this.termsList.length;
        const edited = this.termsList.filter(t => t.edited).length;
        const confirmed = this.termsList.filter(t => t.confirmed).length;
        const deleted = this.deletedTerms.length;

        DOM.setText('stat-total', total);
        DOM.setText('stat-active', active);
        DOM.setText('stat-edited', edited);
        DOM.setText('stat-confirmed', confirmed);
        DOM.setText('stat-deleted', deleted);

        const pct = active > 0 ? Math.round((confirmed / active) * 100) : 0;
        const bar = DOM.el('stat-progress-bar');
        if (bar) bar.style.width = pct + '%';
        DOM.setText('stat-progress-pct', `${confirmed}/${active} (${pct}%)`);
    },

    _updateRecycleCount() {
        DOM.setText('recycle-count', this.deletedTerms.length);
    },

    // ==================== Term Actions ====================

    _handleTargetEdit(key, newValue) {
        const term = this.termsList.find(t => t.key === key);
        if (!term) return;
        term.target = newValue;
        term.edited = true;
        term.confirmed = false;
        this._scheduleAutoSave();
        this._updateStats();
        // Update row styling without full re-render
        const tr = document.querySelector(`tr[data-key="${CSS.escape(key)}"]`);
        if (tr) {
            tr.classList.remove('row-confirmed', 'row-edited');
            tr.classList.add('row-edited');
            const tarInput = tr.querySelector('.col-target .term-input');
            if (tarInput) {
                tarInput.className = 'term-input edited';
            }
            const btnConfirm = tr.querySelector('.btn-confirm');
            if (btnConfirm) {
                btnConfirm.classList.remove('confirmed');
                btnConfirm.title = 'Confirm';
            }
        }
    },

    _confirmTerm(key, forceConfirm = false) {
        const term = this.termsList.find(t => t.key === key);
        if (!term) return;
        if (!term.target || !term.target.trim()) {
            DOM.showToast('Please enter a target term before confirming.', 'warning');
            return;
        }
        if (forceConfirm) {
            if (!term.confirmed) {
                term.confirmed = true;
                term.edited = true;
            }
        } else {
            term.confirmed = !term.confirmed;
            if (term.confirmed) term.edited = true;
        }
        this._scheduleAutoSave();
        this._updateStats();
        // Update row in place
        const tr = document.querySelector(`tr[data-key="${CSS.escape(key)}"]`);
        if (tr) {
            tr.classList.remove('row-confirmed', 'row-edited');
            if (term.confirmed) tr.classList.add('row-confirmed');
            else if (term.edited) tr.classList.add('row-edited');
            const tarInput = tr.querySelector('.col-target .term-input');
            if (tarInput) {
                tarInput.className = 'term-input' + (term.edited ? ' edited' : '') + (term.confirmed ? ' confirmed' : '');
            }
            const btnConfirm = tr.querySelector('.btn-confirm');
            if (btnConfirm) {
                btnConfirm.className = 'btn-confirm' + (term.confirmed ? ' confirmed' : '');
                btnConfirm.title = term.confirmed ? 'Confirmed – click to un-confirm' : 'Confirm';
            }
        }
    },

    _deleteTerm(key) {
        const idx = this.termsList.findIndex(t => t.key === key);
        if (idx === -1) return;
        const term = this.termsList[idx];
        this.deletedTerms.push({ key: term.key, data: term.data, source: term.source, target: term.target });
        delete this.termsData[key];
        this.termsList.splice(idx, 1);
        this._applyFilters();
        this._renderTable();
        this._updateStats();
        this._updateRecycleCount();
        this._scheduleAutoSave();
    },

    _restoreTerm(key) {
        const idx = this.deletedTerms.findIndex(d => d.key === key);
        if (idx === -1) return;
        const deleted = this.deletedTerms[idx];
        this.termsData[deleted.key] = deleted.data;
        this.deletedTerms.splice(idx, 1);
        this._buildTermsList(this._buildSessionMeta());
        this._applyFilters();
        this._renderTable();
        this._updateStats();
        this._updateRecycleCount();
        this._scheduleAutoSave();
        this._openRecycleBin(); // Refresh modal
    },

    _focusNext(key) {
        const idx = this.filteredList.findIndex(t => t.key === key);
        if (idx >= 0 && idx < this.filteredList.length - 1) {
            const nextKey = this.filteredList[idx + 1].key;
            const nextTr = document.querySelector(`tr[data-key="${CSS.escape(nextKey)}"]`);
            if (nextTr) {
                const inp = nextTr.querySelector('.col-target .term-input');
                if (inp) { inp.focus(); inp.select(); }
            } else {
                // Next term on another page
                this.currentPage++;
                this._renderTable();
                setTimeout(() => {
                    const nextTr2 = document.querySelector(`tr[data-key="${CSS.escape(nextKey)}"]`);
                    if (nextTr2) {
                        const inp = nextTr2.querySelector('.col-target .term-input');
                        if (inp) { inp.focus(); inp.select(); }
                    }
                }, 50);
            }
        }
    },

    // ==================== Candidates Modal ====================

    _openCandidatesModal(key) {
        const term = this.termsList.find(t => t.key === key);
        if (!term) return;
        this._currentCandKey = key;

        DOM.setText('modal-src-term', term.source);

        const body = DOM.el('modal-candidates-body');
        const cands = term.cands || {};
        const sorted = Object.entries(cands).sort((a, b) => (b[1].points || 0) - (a[1].points || 0));

        if (sorted.length === 0) {
            body.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:24px">No candidates available</p>';
        } else {
            let html = '<table class="cands-table"><thead><tr>'
                + '<th>Target</th><th>Hits</th><th>Occ.Ratio</th><th>LLM Score</th><th>Points</th><th>Variants</th><th>Select</th>'
                + '</tr></thead><tbody>';

            sorted.forEach(([candTerm, data]) => {
                const isSelected = term.target === candTerm;
                const occRatio = this._calcOccRatio(data, term.count);
                const llmScore = data.llm_score !== undefined ? (data.llm_score * 100).toFixed(1) + '%' : '-';
                const varCount = data.variants ? data.variants.reduce((n, v) => n + Object.keys(v).length, 0) : 0;

                // Use data-cand-key attribute; event listener attached after HTML insertion
                html += `<tr class="${isSelected ? 'cand-selected' : ''}">
                    <td dir="auto" style="font-weight:600">${this._esc(candTerm)}${isSelected ? ' ✓' : ''}</td>
                    <td>${data.hits || '-'}</td>
                    <td>${occRatio}</td>
                    <td>${llmScore}</td>
                    <td>${data.points ? data.points.toFixed(1) : '-'}</td>
                    <td>${varCount > 0 ? varCount : '-'}</td>
                    <td><button class="cand-select-btn ${isSelected ? 'selected' : ''}" data-cand-key="${this._escAttr(candTerm)}">${isSelected ? 'Selected' : 'Select'}</button></td>
                </tr>`;

                // Variants
                if (data.variants && data.variants.length > 0) {
                    data.variants.forEach(varObj => {
                        Object.entries(varObj).forEach(([vTerm, vData]) => {
                            const vSelected = term.target === vTerm;
                            const vLlm = vData.llm_score !== undefined ? (vData.llm_score * 100).toFixed(1) + '%' : '-';
                            html += `<tr class="cand-variant ${vSelected ? 'cand-selected' : ''}">
                                <td dir="auto">↳ ${this._esc(vTerm)}${vSelected ? ' ✓' : ''}</td>
                                <td>${vData.hits || '-'}</td>
                                <td>-</td>
                                <td>${vLlm}</td>
                                <td>${vData.points ? vData.points.toFixed(1) : '-'}</td>
                                <td><em style="color:var(--text-muted);font-size:11px">variant</em></td>
                                <td><button class="cand-select-btn ${vSelected ? 'selected' : ''}" data-cand-key="${this._escAttr(vTerm)}">${vSelected ? 'Selected' : 'Select'}</button></td>
                            </tr>`;
                        });
                    });
                }
            });

            html += '</tbody></table>';
            body.innerHTML = html;

            // Attach event listeners programmatically to avoid inline onclick handlers
            body.querySelectorAll('.cand-select-btn[data-cand-key]').forEach(btn => {
                btn.addEventListener('click', () => this._selectCandidate(btn.dataset.candKey));
            });
        }

        DOM.show('modal-candidates');
    },

    // Calculate occurrence ratio from candidate data
    _calcOccRatio(data, termCount) {
        if (data.count && termCount) return (data.count / termCount).toFixed(2);
        if (data.hits && termCount) return (data.hits / termCount).toFixed(2);
        return '-';
    },

    _selectCandidate(candTerm) {
        const key = this._currentCandKey;
        if (!key) return;
        const term = this.termsList.find(t => t.key === key);
        if (!term) return;
        term.target = candTerm;
        term.edited = true;
        term.confirmed = false;
        this._scheduleAutoSave();
        this._updateStats();
        this._renderTable();
        DOM.hide('modal-candidates');
        this._currentCandKey = null;
        DOM.showToast(`Selected: ${candTerm}`, 'success', 2000);
    },

    // ==================== Recycle Bin ====================

    _openRecycleBin() {
        const body = DOM.el('modal-recycle-body');
        if (this.deletedTerms.length === 0) {
            body.innerHTML = '<p class="recycle-empty">Recycle bin is empty</p>';
        } else {
            const ul = document.createElement('ul');
            ul.className = 'recycle-list';
            this.deletedTerms.forEach(d => {
                const li = document.createElement('li');
                li.className = 'recycle-item';

                const srcSpan = document.createElement('span');
                srcSpan.className = 'recycle-source';
                srcSpan.dir = 'auto';
                srcSpan.textContent = d.source || d.key;

                const tarSpan = document.createElement('span');
                tarSpan.className = 'recycle-target';
                tarSpan.dir = 'auto';
                tarSpan.textContent = d.target || '';

                const restoreBtn = document.createElement('button');
                restoreBtn.className = 'btn-restore';
                restoreBtn.textContent = 'Restore';
                restoreBtn.addEventListener('click', () => this._restoreTerm(d.key));

                li.appendChild(srcSpan);
                li.appendChild(tarSpan);
                li.appendChild(restoreBtn);
                ul.appendChild(li);
            });
            body.innerHTML = '';
            body.appendChild(ul);
        }
        DOM.show('modal-recycle');
    },

    // ==================== Export ====================

    async _exportToExcel(confirmedOnly) {
        const terms = confirmedOnly
            ? this.termsList.filter(t => t.confirmed)
            : this.termsList;

        if (terms.length === 0) {
            DOM.showToast(confirmedOnly ? 'No confirmed terms to export.' : 'No terms to export.', 'warning');
            return;
        }

        const payload = terms.map(t => ({
            source: t.source,
            target: t.target || t.originalTarget,
            status: t.confirmed ? 'Confirmed' : (t.edited ? 'Edited' : 'Unedited'),
            count: t.count,
            hits: t.hits,
            occ_ratio: t.count > 0 ? (t.hits / t.count).toFixed(3) : 0,
        }));

        try {
            const result = await API.exportToExcel(payload, '');
            if (result.success) {
                DOM.showToast(`Exported ${payload.length} terms to Excel`, 'success');
            } else {
                DOM.showToast('Export failed: ' + result.error, 'error');
            }
        } catch (e) {
            DOM.showToast('Export error: ' + e.message, 'error');
        }
    },

    // ==================== Auto-Save ====================

    _scheduleAutoSave() {
        if (this._autoSaveTimer) clearTimeout(this._autoSaveTimer);
        this._autoSaveTimer = setTimeout(() => this._autoSave(), 2000);
    },

    async _autoSave() {
        if (!this.fileMetadata.unique_id) return;
        const meta = this._buildSessionMeta();
        const data = {
            metadata: meta,
            deletedTerms: this.deletedTerms.map(d => ({ key: d.key, data: d.data, source: d.source, target: d.target })),
            timestamp: new Date().toISOString()
        };
        try {
            await API.saveSession(this.fileMetadata.unique_id, data);
            const indicator = DOM.el('autosave-indicator');
            if (indicator) {
                indicator.classList.add('visible');
                setTimeout(() => indicator.classList.remove('visible'), 2000);
            }
        } catch (e) {
            console.error('Auto-save failed:', e);
        }
    },

    _buildSessionMeta() {
        const meta = {};
        this.termsList.forEach(t => {
            if (t.edited || t.confirmed) {
                meta[t.key] = {
                    edited: t.edited,
                    confirmed: t.confirmed,
                    selectedTarget: t.target,
                };
            }
        });
        return meta;
    },

    // ==================== Events ====================

    _bindToolbarEvents() {
        DOM.on('filter-source', 'input', (e) => {
            this.sourceFilter = e.target.value;
            this.currentPage = 1;
            this._applyFilters();
            this._renderTable();
        });

        DOM.on('filter-target', 'input', (e) => {
            this.targetFilter = e.target.value;
            this.currentPage = 1;
            this._applyFilters();
            this._renderTable();
        });

        DOM.on('filter-regex', 'change', (e) => {
            this.useRegex = e.target.checked;
            this._applyFilters();
            this._renderTable();
        });

        DOM.on('filter-status', 'change', (e) => {
            this.currentFilter = e.target.value;
            this.currentPage = 1;
            this._applyFilters();
            this._renderTable();
        });

        DOM.on('per-page', 'change', (e) => {
            this.perPage = parseInt(e.target.value) || 50;
            this.currentPage = 1;
            this._renderTable();
        });

        DOM.on('btn-open-recycle', 'click', () => this._openRecycleBin());
        DOM.on('btn-export-confirmed', 'click', () => this._exportToExcel(true));
        DOM.on('btn-export-all', 'click', () => this._exportToExcel(false));
    },

    _bindPaginationEvents() {
        DOM.on('btn-prev-page', 'click', () => {
            if (this.currentPage > 1) {
                this.currentPage--;
                this._renderTable();
            }
        });

        DOM.on('btn-next-page', 'click', () => {
            const totalPages = Math.ceil(this.filteredList.length / this.perPage) || 1;
            if (this.currentPage < totalPages) {
                this.currentPage++;
                this._renderTable();
            }
        });
    },

    _bindModalEvents() {
        DOM.on('modal-candidates-close', 'click', () => {
            DOM.hide('modal-candidates');
            this._currentCandKey = null;
        });
        DOM.on('modal-candidates-backdrop', 'click', () => {
            DOM.hide('modal-candidates');
            this._currentCandKey = null;
        });
        DOM.on('modal-recycle-close', 'click', () => DOM.hide('modal-recycle'));
        DOM.on('modal-recycle-backdrop', 'click', () => DOM.hide('modal-recycle'));
    },

    // ==================== Helpers ====================

    _getTopCandidate(cands) {
        if (!cands || Object.keys(cands).length === 0) return null;
        const sorted = Object.entries(cands).sort((a, b) => (b[1].points || 0) - (a[1].points || 0));
        return { term: sorted[0][0], ...sorted[0][1] };
    },

    _showLoading(show) {
        if (show) {
            DOM.show('editor-loading');
            DOM.hide('editor-content');
        } else {
            DOM.hide('editor-loading');
        }
    },

    _esc(str) {
        return String(str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    },

    _escAttr(str) {
        // Escape backslashes first, then quotes, to prevent attribute injection
        return String(str || '').replace(/\\/g, '&#92;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
};
