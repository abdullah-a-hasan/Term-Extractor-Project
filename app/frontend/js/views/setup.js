// View 1: Setup – file selection, language pair, extraction method, advanced settings

const Setup = {
    _spacySupported: [],
    _languages: [],

    init() {
        this._bindEvents();
        this._loadLanguages();
        this._loadDefaults();
    },

    _bindEvents() {
        DOM.on('btn-browse-csv', 'click', () => this._browseCsv());
        DOM.on('btn-browse-output', 'click', () => this._browseOutput());
        DOM.on('btn-browse-pred-terms', 'click', () => this._browsePredTerms());
        DOM.on('btn-clear-pred-terms', 'click', () => { DOM.el('pred-terms-path').value = ''; });
        DOM.on('btn-start-extraction', 'click', () => this._startExtraction());

        DOM.on('src-lang', 'change', () => this._checkSpacySupport());
        DOM.on('tar-lang', 'change', () => this._checkSpacySupport());

        // Advanced panel toggle
        DOM.on('advanced-toggle', 'click', () => {
            const body = DOM.el('advanced-settings');
            const icon = DOM.el('advanced-toggle');
            const collapsed = body.style.display === 'none';
            body.style.display = collapsed ? '' : 'none';
            icon.classList.toggle('collapsed', !collapsed);
        });
    },

    async _loadLanguages() {
        try {
            const result = await API.getSupportedLanguages();
            this._languages = result.languages || [];
            this._spacySupported = result.spacy_supported || [];

            const srcSel = DOM.el('src-lang');
            const tarSel = DOM.el('tar-lang');
            srcSel.innerHTML = '<option value="">Select language...</option>';
            tarSel.innerHTML = '<option value="">Select language...</option>';

            this._languages.forEach(lang => {
                srcSel.innerHTML += `<option value="${lang.code}">${lang.name}</option>`;
                tarSel.innerHTML += `<option value="${lang.code}">${lang.name}</option>`;
            });
        } catch (e) {
            console.error('Failed to load languages:', e);
        }
    },

    async _loadDefaults() {
        try {
            const cfg = await API.getDefaultConfig();
            if (!cfg) return;

            const set = (id, val) => { const el = DOM.el(id); if (el) el.value = val; };
            const setChk = (id, val) => { const el = DOM.el(id); if (el) el.checked = val; };

            set('min-source-rep', cfg.min_source_rep);
            set('max-source-rep', cfg.max_source_rep);
            set('min-llm-score', cfg.min_llm_score);
            set('target-dismiss', cfg.target_dismiss);
            set('min-count-ratio', cfg.min_count_ratio);
            set('grouping-min-lev-sim', cfg.grouping_min_lev_sim);
            set('max-sentence-length', cfg.max_sentence_length);
            set('max-translation-pairs', cfg.max_translation_pairs);
            set('skip-top-common-words', cfg.skip_top_common_words);
            setChk('skip-peri-stop-words', cfg.skip_peri_stop_words);
            setChk('llm-scoring', cfg.llm_scoring);
            setChk('enable-partial-points', cfg.enable_partial_points);

            if (cfg.model) {
                const modelEl = DOM.el('model');
                if (modelEl) modelEl.value = cfg.model;
            }

            const method = cfg.src_term_extraction_method || 'ngrams';
            const radio = document.querySelector(`input[name="extraction-method"][value="${method}"]`);
            if (radio) radio.checked = true;
        } catch (e) {
            console.error('Failed to load defaults:', e);
        }
    },

    async _browseCsv() {
        const path = await API.browseCsvFile();
        if (!path) return;
        DOM.el('csv-path').value = path;
        this._previewCsv(path);
    },

    async _previewCsv(path) {
        const preview = DOM.el('csv-preview');
        preview.innerHTML = '<span style="color:#6c757d;font-size:12px">Loading preview...</span>';
        DOM.show(preview);
        try {
            const result = await API.previewCsv(path);
            if (!result.success) {
                preview.innerHTML = `<span style="color:var(--danger)">${result.error}</span>`;
                return;
            }
            let html = `<div class="csv-preview-meta">📊 ${result.row_count.toLocaleString()} rows · ${result.columns} columns</div>`;
            html += '<table class="csv-preview-table"><thead><tr>';
            result.headers.forEach(h => { html += `<th>${this._esc(h)}</th>`; });
            html += '</tr></thead><tbody>';
            result.preview_rows.forEach(row => {
                html += '<tr>';
                row.forEach(cell => { html += `<td>${this._esc(cell)}</td>`; });
                html += '</tr>';
            });
            html += '</tbody></table>';
            preview.innerHTML = html;
        } catch (e) {
            preview.innerHTML = `<span style="color:var(--danger)">Preview error: ${e.message}</span>`;
        }
    },

    async _browseOutput() {
        const path = await API.browseOutputDirectory();
        if (path) DOM.el('output-dir').value = path;
    },

    async _browsePredTerms() {
        const path = await API.browseTermsFile();
        if (path) DOM.el('pred-terms-path').value = path;
    },

    _checkSpacySupport() {
        const srcLang = DOM.val('src-lang');
        const spacyRadio = DOM.el('radio-spacy');
        const warning = DOM.el('spacy-warning');
        const supported = srcLang && this._spacySupported.includes(srcLang);

        if (!supported && spacyRadio) {
            spacyRadio.disabled = true;
            if (spacyRadio.checked) {
                DOM.el('radio-ngrams').checked = true;
            }
            DOM.show(warning);
        } else {
            if (spacyRadio) spacyRadio.disabled = false;
            DOM.hide(warning);
        }
    },

    _buildConfig() {
        const method = document.querySelector('input[name="extraction-method"]:checked');
        return {
            csv_file: DOM.val('csv-path'),
            output_dir: DOM.val('output-dir'),
            src_lang: DOM.val('src-lang'),
            tar_lang: DOM.val('tar-lang'),
            output_name: DOM.val('output-name') || 'extracted_terms',
            pred_terms_file: DOM.val('pred-terms-path'),
            src_term_extraction_method: method ? method.value : 'ngrams',
            min_source_rep: parseInt(DOM.val('min-source-rep')) || 5,
            max_source_rep: parseInt(DOM.val('max-source-rep')) || 30,
            target_dismiss: parseInt(DOM.val('target-dismiss')) || 5,
            min_count_ratio: parseFloat(DOM.val('min-count-ratio')) || 0.4,
            grouping_min_lev_sim: parseFloat(DOM.val('grouping-min-lev-sim')) || 0.7,
            max_sentence_length: parseInt(DOM.val('max-sentence-length')) || 300,
            max_translation_pairs: parseInt(DOM.val('max-translation-pairs')) || 0,
            skip_top_common_words: parseInt(DOM.val('skip-top-common-words')) || 10000,
            skip_peri_stop_words: DOM.checked('skip-peri-stop-words'),
            model: DOM.val('model') || 'LaBSE',
            llm_scoring: DOM.checked('llm-scoring'),
            min_llm_score: parseFloat(DOM.val('min-llm-score')) || 0.4,
            enable_partial_points: DOM.checked('enable-partial-points'),
        };
    },

    _validate(cfg) {
        if (!cfg.csv_file) return 'Please select a CSV file.';
        if (!cfg.output_dir) return 'Please select an output directory.';
        if (!cfg.src_lang) return 'Please select a source language.';
        if (!cfg.tar_lang) return 'Please select a target language.';
        if (cfg.src_lang === cfg.tar_lang) return 'Source and target languages must be different.';
        return null;
    },

    async _startExtraction() {
        const cfg = this._buildConfig();
        const err = this._validate(cfg);
        const msgEl = DOM.el('setup-validation-msg');

        if (err) {
            msgEl.textContent = '⚠ ' + err;
            DOM.show(msgEl);
            return;
        }
        DOM.hide(msgEl);

        try {
            const started = await API.startExtraction(cfg);
            if (started) {
                App.navigateTo('progress');
                Progress.startPolling();
            } else {
                msgEl.textContent = 'Extraction already running.';
                DOM.show(msgEl);
            }
        } catch (e) {
            msgEl.textContent = 'Failed to start extraction: ' + e.message;
            DOM.show(msgEl);
        }
    },

    _esc(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }
};
