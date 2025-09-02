document.getElementById('loginForm').addEventListener('submit', function (e) {
    const btn = document.getElementById('loginBtn');
    btn.classList.add('loading');
    btn.innerHTML = 'Signing In...';
});

// Add some interactive effects
document.querySelectorAll('.form-control').forEach(input => {
    input.addEventListener('focus', function () {
        this.parentElement.style.transform = 'scale(1.02)';
    });

    input.addEventListener('blur', function () {
        this.parentElement.style.transform = 'scale(1)';
    });
});