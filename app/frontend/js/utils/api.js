// Wrapper around window.pywebview.api calls

const API = {
    _ready: false,
    _queue: [],

    init() {
        if (window.pywebview && window.pywebview.api) {
            this._ready = true;
            this._flush();
        } else {
            window.addEventListener('pywebviewready', () => {
                this._ready = true;
                this._flush();
            });
        }
    },

    _flush() {
        this._queue.forEach(({ method, args, resolve, reject }) => {
            this._call(method, args).then(resolve).catch(reject);
        });
        this._queue = [];
    },

    _call(method, args = []) {
        if (!window.pywebview || !window.pywebview.api) {
            return new Promise((resolve, reject) => {
                this._queue.push({ method, args, resolve, reject });
            });
        }
        const fn = window.pywebview.api[method];
        if (!fn) return Promise.reject(new Error(`API method not found: ${method}`));
        return Promise.resolve(fn(...args));
    },

    getSupportedLanguages: () => API._call('get_supported_languages'),
    getDefaultConfig: () => API._call('get_default_config'),
    browseCsvFile: () => API._call('browse_csv_file'),
    browseOutputDirectory: () => API._call('browse_output_directory'),
    browseTermsFile: () => API._call('browse_terms_file'),
    browseJsonFile: () => API._call('browse_json_file'),
    previewCsv: (path) => API._call('preview_csv', [path]),
    startExtraction: (config) => API._call('start_extraction', [config]),
    cancelExtraction: () => API._call('cancel_extraction'),
    getExtractionStatus: () => API._call('get_extraction_status'),
    getLastResultPath: () => API._call('get_last_result_path'),
    loadTermsJson: (path) => API._call('load_terms_json', [path]),
    saveTermsJson: (path, data) => API._call('save_terms_json', [path, data]),
    saveSession: (uniqueId, data) => API._call('save_session', [uniqueId, data]),
    loadSession: (uniqueId) => API._call('load_session', [uniqueId]),
    exportToExcel: (terms, path) => API._call('export_to_excel', [terms, path]),
};

document.addEventListener('DOMContentLoaded', () => API.init());
