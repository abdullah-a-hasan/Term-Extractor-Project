// View 2: Progress – polls extraction status, shows pipeline steps and log

const Progress = {
    STEPS: [
        "Preparing source terms",
        "Pairing source/target",
        "Sorting candidates",
        "Grouping variants",
        "LLM Scoring",
        "Final cleanup",
    ],

    _pollInterval: null,
    _logLinesShown: 0,

    init() {
        this._renderSteps();

        DOM.on('btn-cancel-extraction', 'click', async () => {
            await API.cancelExtraction();
            DOM.setText('progress-label', 'Cancelling...');
        });

        DOM.on('btn-clear-log', 'click', () => {
            DOM.el('log-output').innerHTML = '';
            this._logLinesShown = 0;
        });

        DOM.on('btn-back-to-setup', 'click', () => {
            this.stopPolling();
            App.navigateTo('setup');
        });

        DOM.on('btn-back-to-setup-error', 'click', () => {
            this.stopPolling();
            App.navigateTo('setup');
        });

        DOM.on('btn-review-terms', 'click', async () => {
            this.stopPolling();
            await Editor.loadFromLastResult();
            App.navigateTo('editor');
        });
    },

    _renderSteps() {
        const container = DOM.el('pipeline-steps');
        if (!container) return;
        let html = '';
        this.STEPS.forEach((name, i) => {
            if (i > 0) html += '<span class="pipeline-step-arrow">›</span>';
            html += `<div class="pipeline-step" id="step-${i}">
                <span class="pipeline-step-num">${i + 1}</span>
                <span>${name}</span>
            </div>`;
        });
        container.innerHTML = html;
    },

    startPolling() {
        // Reset UI
        this._logLinesShown = 0;
        DOM.el('log-output').innerHTML = '';
        DOM.el('main-progress-bar').style.width = '0%';
        DOM.setText('progress-label', 'Initializing...');
        DOM.setText('progress-pct', '0%');
        DOM.setText('elapsed-time', '⏱ 0s');
        DOM.hide('completion-card');
        DOM.hide('error-card');
        DOM.hide('terms-found');
        DOM.show('btn-cancel-extraction');

        this.STEPS.forEach((_, i) => {
            const el = DOM.el(`step-${i}`);
            if (el) { el.classList.remove('active', 'completed'); }
        });

        this.stopPolling();
        this._pollInterval = setInterval(() => this._poll(), 500);
    },

    stopPolling() {
        if (this._pollInterval) {
            clearInterval(this._pollInterval);
            this._pollInterval = null;
        }
    },

    async _poll() {
        try {
            const status = await API.getExtractionStatus();
            this._updateUI(status);

            if (status.is_complete || status.is_error) {
                this.stopPolling();
            }
        } catch (e) {
            console.error('Poll error:', e);
        }
    },

    _updateUI(status) {
        // Progress bar
        const pct = status.progress_pct || 0;
        DOM.el('main-progress-bar').style.width = pct + '%';
        DOM.setText('progress-pct', pct + '%');
        DOM.setText('progress-label', status.step_name || 'Running...');
        DOM.setText('elapsed-time', `⏱ ${status.elapsed_seconds}s`);

        if (status.terms_count > 0) {
            DOM.show('terms-found');
            DOM.setText('terms-found-count', status.terms_count);
        }

        // Pipeline steps
        const currentStep = status.step || 0;
        this.STEPS.forEach((_, i) => {
            const el = DOM.el(`step-${i}`);
            if (!el) return;
            el.classList.remove('active', 'completed');
            if (i < currentStep) el.classList.add('completed');
            else if (i === currentStep && status.is_running) el.classList.add('active');
        });

        // Log
        this._appendLog(status.log_lines || []);

        // Completion
        if (status.is_complete) {
            DOM.hide('btn-cancel-extraction');
            DOM.show('completion-card');
            DOM.setText('completion-summary',
                `Found ${status.terms_count} terms. Results saved to output directory.`);
        }

        // Error
        if (status.is_error) {
            DOM.hide('btn-cancel-extraction');
            DOM.show('error-card');
            DOM.setText('error-message', status.error_msg || 'An unknown error occurred.');
        }
    },

    _appendLog(lines) {
        if (!lines || lines.length === 0) return;
        const logEl = DOM.el('log-output');
        const newLines = lines.slice(this._logLinesShown);
        if (newLines.length === 0) return;

        newLines.forEach(line => {
            const span = document.createElement('span');
            span.className = 'log-line' + (line.startsWith('ERROR') ? ' error' : line.includes('complete') ? ' success' : '');
            span.textContent = line + '\n';
            logEl.appendChild(span);
        });

        this._logLinesShown = lines.length;
        logEl.scrollTop = logEl.scrollHeight;
    }
};
