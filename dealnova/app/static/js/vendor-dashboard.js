/**
 * Vendor Dashboard - Script principal
 * Gestion fluide sans rechargement de page
 */

(function() {
    'use strict';
    
    // Configuration
    const CONFIG = {
        searchDelay: 300,
        statsRefreshInterval: 30000,
        stockCheckInterval: 60000,
        lowStockThreshold: 10
    };
    
    // Cache DOM elements
    const DOM = {
        searchInput: document.getElementById('searchInput'),
        searchClear: document.getElementById('searchClear'),
        productsContainer: document.getElementById('productsContainer'),
        productCount: document.getElementById('productCount'),
        categoriesFilter: document.getElementById('categoriesFilter'),
        loadingOverlay: document.getElementById('loadingOverlay'),
        stockToast: document.getElementById('stockToast'),
        stockToastText: document.getElementById('stockToastText'),
        soundToggle: document.getElementById('soundToggle'),
        statOrders: document.getElementById('statOrders'),
        statRevenue: document.getElementById('statRevenue')
    };
    
    // State
    let state = {
        currentCategory: 'all',
        searchTimeout: null,
        soundEnabled: localStorage.getItem('vendorStockSound') !== '0',
        lastLowStockProducts: new Set(),
        isSearching: false
    };
    
    /**
     * Audio Manager
     */
    const AudioManager = {
        context: null,
        
        init() {
            try {
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                this.context = new AudioCtx();
            } catch (e) {
                console.log('Web Audio API not supported');
            }
        },
        
        playStockAlert() {
            if (!state.soundEnabled || !this.context) return;
            
            try {
                const now = this.context.currentTime;
                
                // Première note
                this.playNote(800, now, 0.2);
                
                // Deuxième note (plus haute)
                this.playNote(1000, now + 0.15, 0.2);
                
                // Troisième note (descente)
                this.playNote(900, now + 0.3, 0.15);
            } catch (e) {
                console.log('Failed to play sound:', e);
            }
        },
        
        playNote(frequency, startTime, duration) {
            const osc = this.context.createOscillator();
            const gain = this.context.createGain();
            
            osc.type = 'sine';
            osc.frequency.value = frequency;
            gain.gain.value = 0.0001;
            
            osc.connect(gain);
            gain.connect(this.context.destination);
            
            osc.start(startTime);
            gain.gain.exponentialRampToValueAtTime(0.15, startTime + 0.05);
            gain.gain.exponentialRampToValueAtTime(0.0001, startTime + duration);
            osc.stop(startTime + duration + 0.02);
        },
        
        playSuccess() {
            if (!state.soundEnabled || !this.context) return;
            
            try {
                const now = this.context.currentTime;
                this.playNote(523, now, 0.1);
                this.playNote(659, now + 0.1, 0.15);
            } catch (e) {
                console.log('Failed to play sound:', e);
            }
        }
    };
    
    /**
     * Toast Manager
     */
    const ToastManager = {
        show(message, type = 'info') {
            const toast = document.createElement('div');
            toast.className = `toast-notification toast-${type}`;
            toast.innerHTML = `
                <i class="fas fa-${this.getIcon(type)}"></i>
                <span>${message}</span>
            `;
            
            toast.style.cssText = `
                position: fixed;
                top: 20px;
                right: 20px;
                background: ${this.getColor(type)};
                color: white;
                padding: 1rem 1.5rem;
                border-radius: 12px;
                box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
                display: flex;
                align-items: center;
                gap: 0.75rem;
                z-index: 10001;
                max-width: 350px;
                animation: slideInRight 0.3s ease;
                font-size: 0.9rem;
                font-weight: 600;
            `;
            
            document.body.appendChild(toast);
            
            setTimeout(() => {
                toast.style.animation = 'slideOutRight 0.3s ease';
                setTimeout(() => toast.remove(), 300);
            }, 3000);
        },
        
        getIcon(type) {
            const icons = {
                success: 'check-circle',
                error: 'exclamation-circle',
                warning: 'triangle-exclamation',
                info: 'info-circle'
            };
            return icons[type] || 'info-circle';
        },
        
        getColor(type) {
            const colors = {
                success: '#10B981',
                error: '#EF4444',
                warning: '#F59E0B',
                info: '#3B82F6'
            };
            return colors[type] || '#3B82F6';
        },
        
        showStockAlert(productName, stock) {
            if (!DOM.stockToast || !DOM.stockToastText) return;
            
            DOM.stockToastText.textContent = `${productName} - Stock: ${stock}`;
            DOM.stockToast.classList.add('show');
            AudioManager.playStockAlert();
            
            setTimeout(() => {
                DOM.stockToast.classList.remove('show');
            }, 4000);
        }
    };
    
    /**
     * Sound Toggle
     */
    const SoundToggle = {
        init() {
            if (!DOM.soundToggle) return;
            
            this.update();
            DOM.soundToggle.addEventListener('click', () => this.toggle());
        },
        
        toggle() {
            state.soundEnabled = !state.soundEnabled;
            localStorage.setItem('vendorStockSound', state.soundEnabled ? '1' : '0');
            this.update();
            
            if (state.soundEnabled) {
                AudioManager.playStockAlert();
            }
        },
        
        update() {
            if (!DOM.soundToggle) return;
            
            DOM.soundToggle.innerHTML = state.soundEnabled 
                ? '<i class="fas fa-volume-up"></i>' 
                : '<i class="fas fa-volume-mute"></i>';
            DOM.soundToggle.classList.toggle('muted', !state.soundEnabled);
            DOM.soundToggle.title = state.soundEnabled 
                ? 'Désactiver les notifications sonores' 
                : 'Activer les notifications sonores';
        }
    };
    
    /**
     * Stock Monitor
     */
    const StockMonitor = {
        check() {
            const lowStockCards = document.querySelectorAll('.status-low-stock, .status-out-stock');
            const currentLowStock = new Set();
            
            lowStockCards.forEach(card => {
                const productCard = card.closest('.product-card');
                if (!productCard) return;
                
                const productId = productCard.dataset.productId;
                currentLowStock.add(productId);
                
                // Nouvelle alerte si le produit n'était pas en stock faible avant
                if (!state.lastLowStockProducts.has(productId)) {
                    const productName = productCard.querySelector('.product-title')?.textContent.trim();
                    const stockNumber = productCard.querySelector('.stock-number')?.textContent.trim();
                    
                    if (productName && stockNumber) {
                        ToastManager.showStockAlert(productName, stockNumber);
                    }
                }
            });
            
            state.lastLowStockProducts = currentLowStock;
        }
    };
    
    /**
     * Categories Manager
     */
    const CategoriesManager = {
        load() {
            const url = new URL(window.location.href);
            url.searchParams.set('get_categories', '1');
            
            fetch(url, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(r => r.json())
            .then(data => {
                if (data.categories) {
                    this.render(data.categories);
                }
            })
            .catch(err => console.log('Categories not available:', err));
        },
        
        render(categories) {
            if (!DOM.categoriesFilter) return;
            
            categories.forEach(cat => {
                const chip = document.createElement('div');
                chip.className = 'category-chip';
                chip.dataset.category = cat.id;
                chip.innerHTML = `
                    <i class="fas fa-tag"></i>
                    <span>${this.escapeHtml(cat.name)}</span>
                    <span class="category-badge">${cat.count}</span>
                `;
                chip.addEventListener('click', () => this.select(cat.id, chip));
                DOM.categoriesFilter.appendChild(chip);
            });
        },
        
        select(categoryId, chip) {
            document.querySelectorAll('.category-chip').forEach(c => 
                c.classList.remove('active')
            );
            chip.classList.add('active');
            state.currentCategory = categoryId;
            SearchManager.perform();
        },
        
        escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
    };
    
    /**
     * Search Manager
     */
    const SearchManager = {
        init() {
            if (!DOM.searchInput) return;
            
            DOM.searchInput.addEventListener('input', () => this.handleInput());
            DOM.searchInput.addEventListener('keydown', (e) => this.handleKeydown(e));
            
            if (DOM.searchClear) {
                DOM.searchClear.addEventListener('click', () => this.clear());
            }
            
            // Global "/" shortcut
            document.addEventListener('keydown', (e) => {
                if (e.key === '/' && !e.ctrlKey && !e.metaKey && 
                    document.activeElement !== DOM.searchInput) {
                    e.preventDefault();
                    DOM.searchInput.focus();
                }
            });
        },
        
        handleInput() {
            clearTimeout(state.searchTimeout);
            state.searchTimeout = setTimeout(() => this.perform(), CONFIG.searchDelay);
        },
        
        handleKeydown(e) {
            if (e.key === 'Escape') {
                this.clear();
            }
        },
        
        clear() {
            if (!DOM.searchInput) return;
            
            DOM.searchInput.value = '';
            if (DOM.searchClear) {
                DOM.searchClear.classList.remove('visible');
            }
            this.perform();
            DOM.searchInput.focus();
        },
        
        async perform() {
            if (state.isSearching) return;
            
            const searchTerm = DOM.searchInput?.value.trim() || '';
            
            // Update clear button
            if (DOM.searchClear) {
                DOM.searchClear.classList.toggle('visible', searchTerm.length > 0);
            }
            
            // Show loading
            this.setLoading(true);
            state.isSearching = true;
            
            try {
                const params = new URLSearchParams();
                if (searchTerm) params.append('q', searchTerm);
                if (state.currentCategory !== 'all') {
                    params.append('category', state.currentCategory);
                }
                
                // Get search URL from template or use default
                const searchUrl = document.body.dataset.searchUrl || '/vendor/products/search';
                const url = `${searchUrl}?${params.toString()}`;
                
                const response = await fetch(url, {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                });
                
                if (!response.ok) throw new Error('Search failed');
                
                const html = await response.text();
                this.renderResults(html);
                
            } catch (err) {
                console.error('Search error:', err);
                this.renderError();
            } finally {
                this.setLoading(false);
                state.isSearching = false;
            }
        },
        
        renderResults(html) {
            if (!DOM.productsContainer) return;
            
            // Fade out
            DOM.productsContainer.style.opacity = '0';
            
            setTimeout(() => {
                DOM.productsContainer.innerHTML = html;
                
                // Update count
                const count = DOM.productsContainer.querySelectorAll('.product-card').length;
                if (DOM.productCount) {
                    DOM.productCount.textContent = count;
                }
                
                // Fade in
                DOM.productsContainer.style.opacity = '1';
                
                // Reattach events
                EventManager.attach();
                
                // Check stock
                StockMonitor.check();
            }, 100);
        },
        
        renderError() {
            if (!DOM.productsContainer) return;
            
            DOM.productsContainer.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">
                        <i class="fas fa-exclamation-triangle"></i>
                    </div>
                    <h2 class="empty-title">Erreur</h2>
                    <p class="empty-text">Impossible de charger les produits. Veuillez réessayer.</p>
                </div>
            `;
        },
        
        setLoading(loading) {
            if (DOM.loadingOverlay) {
                DOM.loadingOverlay.classList.toggle('active', loading);
            }
        }
    };
    
    /**
     * Stats Manager
     */
    const StatsManager = {
        async refresh() {
            try {
                const statsUrl = document.body.dataset.statsUrl || '/vendor/stats/live';
                const response = await fetch(statsUrl, {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                });
                
                if (!response.ok) return;
                
                const data = await response.json();
                
                if (data.success) {
                    this.update(data);
                }
            } catch (err) {
                console.log('Stats refresh failed:', err);
            }
        },
        
        update(data) {
            if (DOM.statOrders && data.total_orders !== undefined) {
                this.animateValue(DOM.statOrders, data.total_orders);
            }
            
            if (DOM.statRevenue && data.total_revenue !== undefined) {
                this.animateValue(DOM.statRevenue, data.total_revenue);
            }
        },
        
        animateValue(element, newValue) {
            const currentValue = parseInt(element.textContent) || 0;
            if (currentValue === newValue) return;
            
            const duration = 500;
            const steps = 20;
            const stepValue = (newValue - currentValue) / steps;
            const stepDuration = duration / steps;
            
            let current = currentValue;
            let step = 0;
            
            const interval = setInterval(() => {
                step++;
                current += stepValue;
                
                if (step >= steps) {
                    element.textContent = Math.round(newValue);
                    clearInterval(interval);
                } else {
                    element.textContent = Math.round(current);
                }
            }, stepDuration);
        }
    };
    
    /**
     * Event Manager
     */
    const EventManager = {
        attach() {
            // Delete forms
            document.querySelectorAll('form[data-confirm]').forEach(form => {
                if (form.dataset.bound) return;
                
                form.dataset.bound = 'true';
                form.addEventListener('submit', function(e) {
                    if (!confirm(this.dataset.confirm)) {
                        e.preventDefault();
                    } else {
                        // Show loading on successful confirm
                        SearchManager.setLoading(true);
                    }
                });
            });
        }
    };
    
    /**
     * Initialization
     */
    function init() {
        console.log('🚀 Initializing Vendor Dashboard...');
        
        // Init modules
        AudioManager.init();
        SoundToggle.init();
        SearchManager.init();
        CategoriesManager.load();
        EventManager.attach();
        
        // Initial stock check
        StockMonitor.check();
        
        // Set up intervals
        setInterval(() => StatsManager.refresh(), CONFIG.statsRefreshInterval);
        setInterval(() => StockMonitor.check(), CONFIG.stockCheckInterval);
        
        // Add CSS animations
        addAnimationStyles();
        
        console.log('✨ Dashboard ready!');
    }
    
    /**
     * Add CSS animations
     */
    function addAnimationStyles() {
        const style = document.createElement('style');
        style.textContent = `
            @keyframes slideInRight {
                from {
                    opacity: 0;
                    transform: translateX(100%);
                }
                to {
                    opacity: 1;
                    transform: translateX(0);
                }
            }
            
            @keyframes slideOutRight {
                from {
                    opacity: 1;
                    transform: translateX(0);
                }
                to {
                    opacity: 0;
                    transform: translateX(100%);
                }
            }
            
            .products-grid {
                transition: opacity 0.2s ease;
            }
        `;
        document.head.appendChild(style);
    }
    
    // Start when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
    
    // Expose API for debugging
    window.VendorDashboard = {
        search: () => SearchManager.perform(),
        refreshStats: () => StatsManager.refresh(),
        checkStock: () => StockMonitor.check(),
        playSound: () => AudioManager.playStockAlert()
    };
    
})();