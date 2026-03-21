document.addEventListener('DOMContentLoaded', function() {
    if (window.__BM_TRACK_PHONE_INIT__) return;
    window.__BM_TRACK_PHONE_INIT__ = true;

    const phoneInput = document.querySelector('.phone-input');
    const countryCodeInput = document.getElementById('country_code');
    const flagBadge = document.getElementById('flag_badge');
    const phoneFull = document.getElementById('phone_full');
    const phoneHint = document.getElementById('phone_validation_hint');
    const form = document.querySelector('.tracking-form');
    const countryOptions = Array.from(document.querySelectorAll('#country_codes option'));

    if (!phoneInput || !countryCodeInput || !flagBadge || !phoneFull) return;

    function getPhoneLib() {
        return window.libphonenumber || window.libphonenumberJs || window.libphonenumberjs || null;
    }

    function parseIntl(value) {
        const lib = getPhoneLib();
        if (!lib || typeof lib.parsePhoneNumberFromString !== 'function') return null;
        try {
            return lib.parsePhoneNumberFromString(value);
        } catch (_) {
            return null;
        }
    }

    function setPhoneHint(message, state) {
        if (!phoneHint) return;
        phoneHint.textContent = message || '';
        phoneHint.classList.remove('text-danger', 'text-warning', 'text-success', 'text-muted');
        if (state === 'ok') phoneHint.classList.add('text-success');
        else if (state === 'warn') phoneHint.classList.add('text-warning');
        else if (state === 'error') phoneHint.classList.add('text-danger');
        else phoneHint.classList.add('text-muted');
    }

    function digitsOnly(value) {
        return (value || '').replace(/\D/g, '');
    }

    function sanitizeLocal(value) {
        let v = value || '';
        v = v.replace(/[^\d+\s().-]/g, '');
        v = v.replace(/\s{2,}/g, ' ');
        return v.substring(0, 32);
    }

    function cleanIntlCandidate(value) {
        let v = (value || '').trim();
        v = v.replace(/[^\d+\s().-]/g, '');
        v = v.replace(/\s+/g, '');
        if (v.startsWith('00')) v = '+' + v.slice(2);
        if (v.startsWith('+00')) v = '+' + v.slice(3);
        return v;
    }

    function normalizeCode(value) {
        let v = (value || '').trim();
        if (!v) return '';
        v = v.replace(/[^\d+ ]/g, '');
        v = v.replace(/\s+/g, '');
        if (v && !v.startsWith('+')) v = '+' + digitsOnly(v);
        return v;
    }

    function updateFlag() {
        const code = normalizeCode(countryCodeInput.value);
        const digits = digitsOnly(code);
        let flag = 'GL';
        if (digits) {
            const match = countryOptions.find(o => digitsOnly(o.value) === digits);
            if (match && match.dataset.flag) flag = match.dataset.flag;
        }
        flagBadge.textContent = flag;
    }

    function normalizeLocalAgainstCode(localDigits, codeDigits) {
        let digits = localDigits || '';
        if (!digits) return '';
        if (codeDigits && digits.startsWith('00' + codeDigits)) {
            digits = digits.slice(codeDigits.length + 2);
        } else if (codeDigits && digits.startsWith(codeDigits) && digits.length > codeDigits.length + 4) {
            digits = digits.slice(codeDigits.length);
        }
        if (codeDigits && digits.startsWith('0')) {
            digits = digits.replace(/^0+/, '');
        }
        return digits;
    }

    function splitIfFull(value) {
        const candidate = cleanIntlCandidate(value);
        if (!candidate.startsWith('+')) return null;

        const parsed = parseIntl(candidate);
        if (parsed && parsed.countryCallingCode) {
            countryCodeInput.value = '+' + parsed.countryCallingCode;
            updateFlag();
            return String(parsed.nationalNumber || '');
        }

        const digits = digitsOnly(candidate);
        if (!digits) return null;
        const options = countryOptions
            .map(o => normalizeCode(o.value))
            .filter(Boolean)
            .sort((a, b) => b.length - a.length);

        const match = options.find(v => digits.startsWith(digitsOnly(v)));
        if (match) {
            countryCodeInput.value = match;
            updateFlag();
            return digits.slice(digitsOnly(match).length);
        }

        countryCodeInput.value = '+' + digits.slice(0, Math.min(4, digits.length));
        updateFlag();
        return digits.slice(Math.min(4, digits.length));
    }

    function updateValidation(fullValue) {
        const normalized = cleanIntlCandidate(fullValue);
        if (!normalized) {
            setPhoneHint('Saisissez un numero local ou international.', 'neutral');
            return;
        }

        const parsed = parseIntl(normalized);
        if (parsed && typeof parsed.isValid === 'function' && parsed.isValid()) {
            setPhoneHint('Numero valide.', 'ok');
            return;
        }
        if (parsed && typeof parsed.isPossible === 'function' && parsed.isPossible()) {
            setPhoneHint('Numero possible, verifiez la longueur.', 'warn');
            return;
        }

        const digits = digitsOnly(normalized);
        if (digits.length >= 6 && digits.length <= 15) {
            setPhoneHint('Numero incomplet ou pays non detecte.', 'warn');
        } else {
            setPhoneHint('Numero invalide.', 'error');
        }
    }

    function updateFull() {
        let localRaw = sanitizeLocal(phoneInput.value || '');
        const split = splitIfFull(localRaw);
        if (split !== null) {
            localRaw = split;
            phoneInput.value = split;
        }

        const code = normalizeCode(countryCodeInput.value);
        const codeDigits = digitsOnly(code);
        const localDigits = normalizeLocalAgainstCode(digitsOnly(localRaw), codeDigits);

        if (codeDigits) {
            phoneFull.value = '+' + codeDigits + localDigits;
        } else {
            const fallback = cleanIntlCandidate(localRaw);
            phoneFull.value = fallback.startsWith('+') ? fallback : digitsOnly(fallback);
        }

        const parsed = parseIntl(phoneFull.value);
        if (parsed && parsed.countryCallingCode) {
            countryCodeInput.value = '+' + parsed.countryCallingCode;
            updateFlag();
            const national = String(parsed.nationalNumber || '');
            if (national) {
                phoneInput.value = national;
                phoneFull.value = '+' + parsed.countryCallingCode + national;
            }
        }

        updateValidation(phoneFull.value);
    }

    phoneInput.addEventListener('input', function(e) {
        e.target.value = sanitizeLocal(e.target.value);
        updateFull();
    });

    countryCodeInput.addEventListener('input', function(e) {
        e.target.value = e.target.value.replace(/[^\d+ ]/g, '').substring(0, 8);
        updateFlag();
        updateFull();
    });

    const remembered = (phoneInput.value || '').trim();
    if (remembered) {
        phoneInput.value = sanitizeLocal(remembered);
    }

    updateFlag();
    updateFull();

    if (form) {
        form.addEventListener('submit', function(e) {
            if (this.dataset.submitted === 'true') {
                e.preventDefault();
                return;
            }
            this.dataset.submitted = 'true';
            updateFull();
            const button = this.querySelector('button[type="submit"]');
            if (button) {
                if (!button.dataset.originalHtml) {
                    button.dataset.originalHtml = button.innerHTML;
                }
                button.innerHTML = `
                    <i class="fas fa-spinner fa-spin"></i>
                    <span>Recherche en cours...</span>
                `;
                button.disabled = true;
            }
        });
    }

    window.addEventListener('pageshow', function(ev) {
        if (!ev.persisted || !form) return;
        form.dataset.submitted = 'false';
        const button = form.querySelector('button[type="submit"]');
        if (!button) return;
        button.disabled = false;
        if (button.dataset.originalHtml) {
            button.innerHTML = button.dataset.originalHtml;
        }
    });
});
