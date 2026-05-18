/**
 * Global Input Validation System
 * Handles real-time validation, visual feedback, and duplicate detection.
 */

class FormValidator {
    constructor(form) {
        this.form = form;
        this.inputs = form.querySelectorAll('input, select, textarea');
        this.submitBtn = form.querySelector('button[type="submit"]');
        this.init();
    }

    init() {
        // Disable HTML5 native validation to use custom styles
        this.form.setAttribute('novalidate', 'true');

        this.inputs.forEach(input => {
            // Real-time validation on input and blur
            input.addEventListener('input', () => this.validateField(input));
            input.addEventListener('blur', () => this.validateField(input));
        });

        this.form.addEventListener('submit', (e) => {
            let isValid = true;
            this.inputs.forEach(input => {
                if (!this.validateField(input)) {
                    isValid = false;
                }
            });

            if (!isValid) {
                e.preventDefault();
                e.stopPropagation();

                // Shake effect for first invalid field
                const firstInvalid = this.form.querySelector('.is-invalid');
                if (firstInvalid) {
                    firstInvalid.focus();
                    firstInvalid.classList.add('shake');
                    setTimeout(() => firstInvalid.classList.remove('shake'), 500);
                }
            }
        });
    }

    validateField(input) {
        // Skip hidden inputs or buttons
        if (input.type === 'hidden' || input.type === 'submit' || input.type === 'button') return true;

        let isValid = true;
        let errorMessage = '';

        const value = input.value.trim();
        const label = input.getAttribute('placeholder') || 'This field';

        // 1. Required Check
        if (input.hasAttribute('required') && !value) {
            isValid = false;
            errorMessage = `${label} is required`;
        }

        // 2. Type-Specific Validation (only if not empty)
        if (isValid && value) {
            // Email Validation
            if (input.type === 'email' || input.getAttribute('data-validate') === 'email') {
                const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
                if (!emailRegex.test(value)) {
                    isValid = false;
                    errorMessage = 'Please enter a valid email address';
                }
            }

            // Numeric Validation
            if (input.type === 'number' || input.getAttribute('data-validate') === 'numeric') {
                if (isNaN(value)) {
                    isValid = false;
                    errorMessage = 'Please enter a valid number';
                }
            }

            // Phone Validation (10 digits)
            if (input.type === 'tel' || input.getAttribute('data-validate') === 'phone') {
                const phoneRegex = /^\d{10}$/;
                if (!phoneRegex.test(value)) {
                    isValid = false;
                    errorMessage = 'Must be exactly 10 digits';
                }
            }

            // Password Complexity
            if (input.type === 'password' && input.getAttribute('data-validate') === 'password') {
                // Min 8 chars, 1 letter, 1 number
                const complexityRegex = /^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d@$!%*#?&]{8,}$/;
                if (!complexityRegex.test(value)) {
                    isValid = false;
                    errorMessage = 'Must be 8+ chars with 1 letter & 1 number';
                }
            }

            // Alphabetic (No numbers/special chars)
            if (input.getAttribute('data-validate') === 'alphabetic') {
                const alphaRegex = /^[a-zA-Z\s]+$/;
                if (!alphaRegex.test(value)) {
                    isValid = false;
                    errorMessage = 'Only letters allowed';
                }
            }

            // Async Uniqueness Check
            if (isValid && input.getAttribute('data-unique-id')) {
                // Return immediate True to allow feedback to persist while check happens
                // or handle it with a promise. For simplicity, we trigger the async check.
                this.checkUniqueness(input);
                return true; // We'll update the visual state later
            }
        }

        this.toggleError(input, isValid, errorMessage);
        return isValid;
    }

    async checkUniqueness(input) {
        const fieldId = input.getAttribute('data-unique-id');
        const value = input.value.trim();
        const recordId = input.getAttribute('data-record-id') || null;

        if (!value) return;

        // Show "Checking..."
        this.toggleError(input, true, 'Checking...');

        try {
            const response = await fetch('/api/check-uniqueness', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': document.querySelector('input[name="csrf_token"]').value
                },
                body: JSON.stringify({
                    field_id: fieldId,
                    value: value,
                    record_id: recordId
                })
            });

            const data = await response.json();
            if (!data.unique) {
                this.toggleError(input, false, 'Already exists. Must be unique.');
            } else {
                this.toggleError(input, true, '');
            }
        } catch (error) {
            console.error('Uniqueness check failed:', error);
        }
    }

    toggleError(input, isValid, message) {
        const parent = input.closest('.mb-3') || input.parentElement;
        let feedback = parent.querySelector('.invalid-feedback');

        if (!feedback) {
            feedback = document.createElement('div');
            feedback.className = 'invalid-feedback';
            parent.appendChild(feedback);
        }

        if (isValid) {
            input.classList.remove('is-invalid');
            input.classList.add('is-valid');
            feedback.style.display = 'none';
        } else {
            input.classList.remove('is-valid');
            input.classList.add('is-invalid');
            feedback.textContent = message;
            feedback.style.display = 'block';
        }
    }
}

// Auto-initialize on DOM Load
document.addEventListener('DOMContentLoaded', () => {
    const forms = document.querySelectorAll('form.needs-validation');
    forms.forEach(form => new FormValidator(form));
});
