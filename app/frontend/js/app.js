// App initialization and view routing

const App = {
    currentView: 'setup',
    views: ['setup', 'progress', 'editor'],

    init() {
        document.querySelectorAll('[data-view]').forEach(el => {
            el.addEventListener('click', () => this.navigateTo(el.dataset.view));
        });

        DOM.on('btn-load-json', 'click', async () => {
            const path = await API.browseJsonFile();
            if (path) {
                await Editor.loadFromPath(path);
                this.navigateTo('editor');
            }
        });

        this.navigateTo('setup');
    },

    navigateTo(viewName) {
        if (!this.views.includes(viewName)) return;

        this.views.forEach(v => {
            const el = document.getElementById(`view-${v}`);
            if (el) el.classList.remove('active');
        });

        const target = document.getElementById(`view-${viewName}`);
        if (target) target.classList.add('active');

        document.querySelectorAll('.step-item').forEach(el => {
            el.classList.remove('active', 'completed');
        });

        const stepMap = { setup: 1, progress: 2, editor: 3 };
        const currentStep = stepMap[viewName] || 1;

        document.querySelectorAll('.step-item').forEach(el => {
            const num = parseInt(el.querySelector('.step-num').textContent);
            if (num < currentStep) el.classList.add('completed');
            else if (num === currentStep) el.classList.add('active');
        });

        this.currentView = viewName;
    }
};

document.addEventListener('DOMContentLoaded', () => {
    App.init();
    Setup.init();
    Progress.init();
    Editor.init();
});
