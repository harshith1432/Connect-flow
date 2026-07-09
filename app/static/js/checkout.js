document.addEventListener('DOMContentLoaded', function() {
    // Sidebar toggle for mobile
    const toggleBtn = document.getElementById('toggle-sidebar-btn');
    const sidebar = document.querySelector('.premium-sidebar');
    
    if (toggleBtn && sidebar) {
        toggleBtn.addEventListener('click', function() {
            sidebar.classList.toggle('active');
        });
    }

    // Payment Methods Tabs (Visual only)
    const methodPills = document.querySelectorAll('.method-pill');
    methodPills.forEach(pill => {
        pill.addEventListener('click', function() {
            methodPills.forEach(p => p.classList.remove('active'));
            this.classList.add('active');
        });
    });

    // Copy UPI ID helper function
    window.copyUpiId = function() {
        const upiId = document.getElementById('upi-display-id').innerText;
        navigator.clipboard.writeText(upiId).then(() => {
            alert('UPI ID copied to clipboard!');
        }).catch(err => {
            console.error('Failed to copy UPI ID: ', err);
        });
    };

    // Monitor gateway selection changes
    const gatewayRadios = document.querySelectorAll('input[name="gateway_id"]');
    const upiContainer = document.getElementById('dynamic-upi-container');
    const submitBtnText = document.getElementById('button-text');

    function updateGatewayView() {
        const selected = document.querySelector('input[name="gateway_id"]:checked');
        if (!selected) return;

        const provider = selected.dataset.provider;
        if (provider === 'dynamic_upi') {
            if (upiContainer) upiContainer.style.display = 'block';
            if (submitBtnText) submitBtnText.innerText = 'Submit Payment for Verification';
            
            // Build QR Code details
            const upiId = selected.dataset.upiId || 'merchant@upi';
            const merchantName = selected.dataset.merchantName || 'CalltoConvey';
            const qrSize = selected.dataset.qrSize || '250';
            const msg = selected.dataset.verificationTimeMsg || 'Usually 2–15 minutes.';
            const totalAmount = document.getElementById('checkout-total-val').dataset.amount;
            const planId = document.getElementById('plan_id').value;
            
            // Generate unique reference number if not already present
            let refNum = document.getElementById('upi-display-ref').innerText;
            if (!refNum || refNum === 'REF-0000') {
                refNum = `CF-${planId}-${Date.now()}`;
            }

            // Set DOM values
            document.getElementById('upi-display-amount').innerText = `₹${parseFloat(totalAmount).toFixed(2)}`;
            document.getElementById('upi-display-ref').innerText = refNum;
            document.getElementById('upi-display-id').innerText = upiId;
            document.getElementById('upi-display-msg').innerText = `Verification Time: ${msg} Your order will start processing only after payment verification is completed.`;
            
            // Generate QR Code URL
            const qrUrl = `https://api.qrserver.com/v1/create-qr-code/?size=${qrSize}x${qrSize}&data=` + encodeURIComponent(`upi://pay?pa=${upiId}&pn=${encodeURIComponent(merchantName)}&am=${totalAmount}&cu=INR&tn=${refNum}`);
            document.getElementById('upi-qr-image').src = qrUrl;
        } else {
            if (upiContainer) upiContainer.style.display = 'none';
            if (submitBtnText) submitBtnText.innerText = 'Proceed to Payment';
        }
    }

    gatewayRadios.forEach(radio => {
        radio.addEventListener('change', updateGatewayView);
    });

    // Run initial update on load
    updateGatewayView();

    // Form submission
    const paymentForm = document.getElementById('payment-form');
    if (paymentForm) {
        paymentForm.addEventListener('submit', function (e) {
            e.preventDefault();
            
            const selectedGateway = document.querySelector('input[name="gateway_id"]:checked');
            if (!selectedGateway) {
                alert('Please select a payment gateway first.');
                return;
            }

            const gatewayId = selectedGateway.value;
            const provider = selectedGateway.dataset.provider;

            const btn = document.getElementById('submit-button');
            const text = document.getElementById('button-text');
            const loader = document.getElementById('loader');

            btn.disabled = true;
            text.innerText = 'Processing...';
            loader.style.display = 'inline-block';

            const planId = document.getElementById('plan_id').value;
            const planName = document.getElementById('plan_name').value;
            const orgName = document.getElementById('org_name').value;
            const orgEmail = document.getElementById('org_email').value;
            const csrfToken = document.getElementById('csrf_token').value;

            function resetBtn() {
                btn.disabled = false;
                text.innerText = provider === 'dynamic_upi' ? 'Submit Payment for Verification' : 'Proceed to Payment';
                loader.style.display = 'none';
            }

            // Handle Dynamic UPI Payment submission
            if (provider === 'dynamic_upi') {
                const txnId = document.getElementById('transaction_id').value.trim();
                const screenshotInput = document.getElementById('screenshot');
                const customerUpi = document.getElementById('customer_upi_id').value.trim();
                const notes = document.getElementById('additional_notes').value.trim();
                const refNum = document.getElementById('upi-display-ref').innerText;
                const totalAmount = document.getElementById('checkout-total-val').dataset.amount;

                if (!txnId) {
                    alert('Please enter the Transaction ID / UTR.');
                    resetBtn();
                    return;
                }
                if (txnId.length < 8) {
                    alert('Please enter a valid Transaction ID (minimum 8 characters).');
                    resetBtn();
                    return;
                }
                if (screenshotInput.files.length === 0) {
                    alert('Please upload a screenshot of your payment receipt.');
                    resetBtn();
                    return;
                }

                const file = screenshotInput.files[0];
                const allowedExtensions = selectedGateway.dataset.acceptedFileTypes ? selectedGateway.dataset.acceptedFileTypes.split(',') : ['jpg', 'jpeg', 'png', 'webp', 'pdf'];
                const fileExt = file.name.split('.').pop().toLowerCase();
                if (!allowedExtensions.includes(fileExt)) {
                    alert('Invalid file format. Accepted formats: ' + allowedExtensions.join(', ').toUpperCase());
                    resetBtn();
                    return;
                }

                const maxMb = parseFloat(selectedGateway.dataset.maxUploadSize) || 10;
                const maxSize = maxMb * 1024 * 1024;
                if (file.size > maxSize) {
                    alert('File size exceeds the ' + maxMb + 'MB limit.');
                    resetBtn();
                    return;
                }

                // Prepare FormData
                const formData = new FormData();
                formData.append('plan_id', planId);
                formData.append('gateway_id', gatewayId);
                formData.append('transaction_id', txnId);
                formData.append('screenshot', file);
                formData.append('customer_upi_id', customerUpi);
                formData.append('additional_notes', notes);
                formData.append('ref_num', refNum);
                formData.append('amount', totalAmount);

                fetch('/api/upi/submit-payment', {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': csrfToken
                    },
                    body: formData
                })
                .then(res => {
                    if (!res.ok) return res.json().then(d => { throw new Error(d.error || 'Failed to submit payment.') });
                    return res.json();
                })
                .then(verifyData => {
                    if (verifyData.success) {
                        alert('Payment submitted successfully! Our team is verifying your transaction. Redirecting to profile...');
                        window.location.href = "/org/profile";
                    } else {
                        alert('Error: ' + (verifyData.error || 'Unknown error'));
                        resetBtn();
                    }
                })
                .catch(err => {
                    alert(err.message);
                    resetBtn();
                });
                return;
            }

            // Handle Standard Gateway payments
            fetch('/api/create-order', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({
                    plan_id: planId,
                    gateway_id: gatewayId
                })
            })
            .then(response => {
                if (!response.ok) throw new Error('Failed to create order.');
                return response.json();
            })
            .then(data => {
                if (data.error) {
                    alert('Error: ' + data.error);
                    resetBtn();
                    return;
                }

                if (provider === 'razorpay') {
                    const options = {
                        "key": data.key_id,
                        "amount": data.amount,
                        "currency": data.currency,
                        "name": "CalltoConvey Premium",
                        "description": "Subscription - " + planName,
                        "order_id": data.order_id,
                        "handler": function (response) {
                            text.innerText = 'Verifying Payment...';
                            
                            fetch('/api/verify-payment', {
                                method: 'POST',
                                headers: {
                                    'Content-Type': 'application/json',
                                    'X-CSRFToken': csrfToken
                                },
                                body: JSON.stringify({
                                    razorpay_payment_id: response.razorpay_payment_id,
                                    razorpay_order_id: response.razorpay_order_id,
                                    razorpay_signature: response.razorpay_signature,
                                    plan_id: planId,
                                    gateway_id: gatewayId
                                })
                            })
                            .then(res => {
                                if (!res.ok) throw new Error('Verification failed.');
                                return res.json();
                            })
                            .then(verifyData => {
                                if (verifyData.success) {
                                    window.location.href = "/org/profile";
                                } else {
                                    alert('Payment Verification Failed: ' + (verifyData.error || 'Unknown error'));
                                    resetBtn();
                                }
                            })
                            .catch(err => {
                                alert(err.message);
                                resetBtn();
                            });
                        },
                        "prefill": {
                            "name": orgName,
                            "email": orgEmail
                        },
                        "theme": {
                            "color": "#000000"
                        },
                        "modal": {
                            "ondismiss": function() {
                                resetBtn();
                            }
                        }
                    };

                    if (typeof Razorpay !== "undefined") {
                        const rzp1 = new Razorpay(options);
                        rzp1.open();
                    } else {
                        alert("Razorpay SDK failed to load. Please check your network.");
                        resetBtn();
                    }
                } else if (provider === 'stripe') {
                    alert("Stripe integration is coming soon!");
                    resetBtn();
                } else {
                    alert("Unknown payment provider.");
                    resetBtn();
                }
            })
            .catch(error => {
                alert(error.message);
                resetBtn();
            });
        });
    }
});
