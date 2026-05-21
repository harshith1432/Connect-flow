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
                        "name": "ConnectFlow Premium",
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
                                    window.location.href = "/org/profile"; // Redirect to dashboard profile
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

            function resetBtn() {
                btn.disabled = false;
                text.innerText = 'Proceed to Payment';
                loader.style.display = 'none';
            }
        });
    }
});
