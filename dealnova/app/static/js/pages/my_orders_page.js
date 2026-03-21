(function() {
    'use strict';
    if (window.__BM_MY_ORDERS_INIT__) return;
    window.__BM_MY_ORDERS_INIT__ = true;

    // Add ripple effect to buttons
    document.querySelectorAll('.btn-action, .btn-order, .btn-discover').forEach(btn => {
        btn.addEventListener('click', function(e) {
            const ripple = document.createElement('span');
            const rect = this.getBoundingClientRect();
            const size = Math.max(rect.width, rect.height);
            const x = e.clientX - rect.left - size / 2;
            const y = e.clientY - rect.top - size / 2;

            ripple.style.cssText = `
                position: absolute;
                width: ${size}px;
                height: ${size}px;
                border-radius: 50%;
                background: rgba(255, 255, 255, 0.6);
                left: ${x}px;
                top: ${y}px;
                transform: scale(0);
                animation: ripple 0.6s ease-out;
                pointer-events: none;
                z-index: 100;
            `;

            this.appendChild(ripple);
            setTimeout(() => ripple.remove(), 600);
        });
    });

    // Add ripple animation
    if (!document.getElementById('ordersRippleStyle')) {
        const style = document.createElement('style');
        style.id = 'ordersRippleStyle';
        style.textContent = `
            @keyframes ripple {
                to {
                    transform: scale(4);
                    opacity: 0;
                }
            }
        `;
        document.head.appendChild(style);
    }

    // Animate order cards on intersection
    if ('IntersectionObserver' in window) {
        const observerOptions = {
            threshold: 0.1,
            rootMargin: '0px 0px -50px 0px'
        };

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.style.opacity = '1';
                    entry.target.style.transform = 'translateY(0)';
                    observer.unobserve(entry.target);
                }
            });
        }, observerOptions);

        document.querySelectorAll('.order-card').forEach(card => {
            observer.observe(card);
        });
    }

    // Copy order ID on click
    document.querySelectorAll('.order-id').forEach(el => {
        el.style.cursor = 'pointer';
        el.title = 'Cliquer pour copier le numéro';
        
        el.addEventListener('click', function(e) {
            if (e.target.closest('.status-badge')) return;
            
            const match = this.textContent.match(/#(\d+)/);
            const orderId = match ? match[1] : null;
            if (orderId) {
                navigator.clipboard.writeText(orderId).then(() => {
                    const feedback = document.createElement('div');
                    feedback.textContent = 'Copi?';
                    feedback.style.cssText = `
                        position: fixed;
                        top: 50%;
                        left: 50%;
                        transform: translate(-50%, -50%);
                        background: rgba(16, 185, 129, 0.95);
                        color: white;
                        padding: 1rem 2rem;
                        border-radius: 12px;
                        font-weight: 700;
                        z-index: 10000;
                        animation: fadeInOut 2s ease;
                        box-shadow: 0 8px 24px rgba(16, 185, 129, 0.4);
                    `;
                    
                    document.body.appendChild(feedback);
                    setTimeout(() => feedback.remove(), 2000);
                }).catch(() => {
                    console.log('Copy failed');
                });
            }
        });
    });

    // Add fadeInOut animation
    if (!document.getElementById('ordersCopyStyle')) {
        const copyStyle = document.createElement('style');
        copyStyle.id = 'ordersCopyStyle';
        copyStyle.textContent = `
            @keyframes fadeInOut {
                0%, 100% { opacity: 0; transform: translate(-50%, -50%) scale(0.8); }
                15%, 85% { opacity: 1; transform: translate(-50%, -50%) scale(1); }
            }
        `;
        document.head.appendChild(copyStyle);
    }

    // Smooth scroll behavior
    document.documentElement.style.scrollBehavior = 'smooth';

    // Performance: Reduce animations on low-end devices
    if (navigator.hardwareConcurrency && navigator.hardwareConcurrency < 4) {
        document.querySelectorAll('.particle-dot').forEach(p => p.remove());
    }
    // Removed legacy auto-refresh block.

    console.log('Orders page loaded successfully');
})();
