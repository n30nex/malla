/**
 * Time Range Presets Component
 * Adds quick filter buttons (1h, 6h, 24h, 7d, 30d) for datetime inputs.
 */

class TimeRangePresets {
    constructor(options = {}) {
        this.options = {
            startTimeSelector: options.startTimeSelector || '#start_time',
            endTimeSelector: options.endTimeSelector || '#end_time',
            containerSelector: options.containerSelector || '#time-presets',
            storageKey: options.storageKey || 'malla_time_preset',
            autoApply: options.autoApply !== false,
            onApply: options.onApply || null,
            ...options
        };

        this.presets = [
            { label: '1h', duration: 3600, title: 'Last 1 Hour' },
            { label: '6h', duration: 3600 * 6, title: 'Last 6 Hours' },
            { label: '24h', duration: 3600 * 24, title: 'Last 24 Hours' },
            { label: '7d', duration: 3600 * 24 * 7, title: 'Last 7 Days' },
            { label: '30d', duration: 3600 * 24 * 30, title: 'Last 30 Days' }
        ];

        this.init();
    }

    init() {
        this.render();
        this.loadPreference();
    }

    render() {
        const container = document.querySelector(this.options.containerSelector);
        if (!container) return;

        // Create button group
        const group = document.createElement('div');
        group.className = 'btn-group btn-group-sm mb-2';
        group.role = 'group';
        group.setAttribute('aria-label', 'Time range presets');

        this.presets.forEach(preset => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-outline-secondary';
            btn.textContent = preset.label;
            btn.title = preset.title;
            btn.dataset.duration = preset.duration;

            btn.addEventListener('click', () => this.applyPreset(preset));

            group.appendChild(btn);
        });

        // Add "All Time" button (clear filters)
        const clearBtn = document.createElement('button');
        clearBtn.type = 'button';
        clearBtn.className = 'btn btn-outline-secondary';
        clearBtn.textContent = 'All';
        clearBtn.title = 'All Time';
        clearBtn.addEventListener('click', () => this.clearTimeRange());
        group.appendChild(clearBtn);

        container.appendChild(group);
        this.container = container;
    }

    applyPreset(preset) {
        const now = new Date();
        const start = new Date(now.getTime() - (preset.duration * 1000));

        // Format for datetime-local input: YYYY-MM-DDTHH:mm
        const format = (date) => {
            const offset = date.getTimezoneOffset() * 60000;
            const localIso = new Date(date.getTime() - offset).toISOString();
            return localIso.slice(0, 16);
        };

        const startInput = document.querySelector(this.options.startTimeSelector);
        const endInput = document.querySelector(this.options.endTimeSelector);

        if (startInput) startInput.value = format(start);
        if (endInput) endInput.value = format(now);

        // Update active state
        this.updateActiveButton(preset.label);

        // Save preference
        localStorage.setItem(this.options.storageKey, preset.label);

        // Trigger change events
        if (startInput) startInput.dispatchEvent(new Event('change', { bubbles: true }));
        if (endInput) endInput.dispatchEvent(new Event('change', { bubbles: true }));

        // Call callback if provided
        if (this.options.onApply) {
            this.options.onApply();
        }
    }

    clearTimeRange() {
        const startInput = document.querySelector(this.options.startTimeSelector);
        const endInput = document.querySelector(this.options.endTimeSelector);

        if (startInput) startInput.value = '';
        if (endInput) endInput.value = '';

        this.updateActiveButton('All');
        localStorage.removeItem(this.options.storageKey);

        if (startInput) startInput.dispatchEvent(new Event('change', { bubbles: true }));
        if (endInput) endInput.dispatchEvent(new Event('change', { bubbles: true }));

        if (this.options.onApply) {
            this.options.onApply();
        }
    }

    updateActiveButton(label) {
        if (!this.container) return;

        const buttons = this.container.querySelectorAll('button');
        buttons.forEach(btn => {
            if (btn.textContent === label) {
                btn.classList.remove('btn-outline-secondary');
                btn.classList.add('btn-secondary', 'active');
            } else {
                btn.classList.add('btn-outline-secondary');
                btn.classList.remove('btn-secondary', 'active');
            }
        });
    }

    loadPreference() {
        const savedLabel = localStorage.getItem(this.options.storageKey);
        if (savedLabel) {
            const preset = this.presets.find(p => p.label === savedLabel);
            if (preset) {
                // Don't auto-apply on load if inputs already have values (e.g. from URL)
                const startInput = document.querySelector(this.options.startTimeSelector);
                if (startInput && !startInput.value && this.options.autoApply) {
                    this.applyPreset(preset);
                } else {
                    // Just highlight the button if it matches roughly
                    this.updateActiveButton(savedLabel);
                }
            }
        }
    }
}

// Export
window.TimeRangePresets = TimeRangePresets;
