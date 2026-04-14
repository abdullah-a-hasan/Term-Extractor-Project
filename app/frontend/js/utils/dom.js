// DOM utility helpers

const DOM = {
    el: (id) => document.getElementById(id),

    show: (el) => {
        if (typeof el === 'string') el = document.getElementById(el);
        if (el) el.classList.remove('hidden');
    },

    hide: (el) => {
        if (typeof el === 'string') el = document.getElementById(el);
        if (el) el.classList.add('hidden');
    },

    toggle: (el, condition) => {
        if (typeof el === 'string') el = document.getElementById(el);
        if (!el) return;
        if (condition) el.classList.remove('hidden');
        else el.classList.add('hidden');
    },

    setText: (id, text) => {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    },

    setHTML: (id, html) => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = html;
    },

    on: (id, event, handler) => {
        const el = typeof id === 'string' ? document.getElementById(id) : id;
        if (el) el.addEventListener(event, handler);
    },

    addClass: (el, cls) => {
        if (typeof el === 'string') el = document.getElementById(el);
        if (el) el.classList.add(cls);
    },

    removeClass: (el, cls) => {
        if (typeof el === 'string') el = document.getElementById(el);
        if (el) el.classList.remove(cls);
    },

    val: (id) => {
        const el = document.getElementById(id);
        return el ? el.value : '';
    },

    checked: (id) => {
        const el = document.getElementById(id);
        return el ? el.checked : false;
    },

    showToast: (msg, type = 'info', duration = 3000) => {
        const toast = document.getElementById('toast');
        if (!toast) return;
        toast.textContent = msg;
        toast.className = `toast toast-${type}`;
        toast.classList.remove('hidden');
        setTimeout(() => toast.classList.add('hidden'), duration);
    }
};
