document.addEventListener('DOMContentLoaded', function () {
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.has('logged_out')) {
        window.history.replaceState({}, document.title, window.location.pathname);
        return;
    }

    if (!isComingFromLogout()) {
        checkAuthenticationStatus();
    }
});

function isComingFromLogout() {
    const urlParams = new URLSearchParams(window.location.search);
    const referrer = document.referrer;

    if (urlParams.has('logged_out') || referrer.includes('/logout')) {
        return true;
    }
    if (window.history.length === 1) {
        return false;
    }

    return false;
}

async function checkAuthenticationStatus() {
    try {
        const response = await fetch('/', {
            method: 'GET',
            cache: 'no-cache',
            headers: {
                'Cache-Control': 'no-cache'
            }
        });

        if (response.url.includes('/login')) {
            console.log('User not logged in, staying on login page');
            return;
        }

        if (response.ok && !response.url.includes('/login')) {
            console.log('User already logged in, redirecting...');
            window.history.replaceState(null, '', '/');
            window.location.replace('/');
        }
    } catch (error) {
        console.log('User not logged in, staying on login page');
    }
}

document.getElementById('loginForm').addEventListener('submit', function (e) {
    const btn = document.getElementById('loginBtn');
    btn.classList.add('loading');
    btn.innerHTML = 'Signing In...';

    setTimeout(() => {
    }, 100);
});

document.querySelectorAll('.form-control').forEach(input => {
    input.addEventListener('focus', function () {
        this.parentElement.style.transform = 'scale(1.02)';
    });

    input.addEventListener('blur', function () {
        this.parentElement.style.transform = 'scale(1)';
    });
});

(function () {
    const flashText = document.getElementById('flashText');
    if (!flashText) return;

    const msg = flashText.textContent;
    const match = msg.match(/Try again in (\d+) seconds/);
    if (!match) return;

    let seconds = parseInt(match[1], 10);

    const btn = document.getElementById('loginBtn');
    const inputs = document.querySelectorAll('#loginForm input');
    btn.disabled = true;
    inputs.forEach(i => i.disabled = true);

    const interval = setInterval(() => {
        seconds--;
        if (seconds <= 0) {
            clearInterval(interval);
            flashText.textContent = 'Lockout expired. You may try again.';
            btn.disabled = false;
            inputs.forEach(i => i.disabled = false);
            document.getElementById('username').focus();
        } else {
            flashText.textContent = msg.replace(/\d+ seconds/, `${seconds} seconds`);
        }
    }, 1000);
})();

window.addEventListener('load', function () {
    console.log('Login page loaded');
});

document.addEventListener('visibilitychange', function () {
    if (!document.hidden) {
        checkAndRedirectIfLoggedIn();
    }
});

async function checkAndRedirectIfLoggedIn() {
    try {
        const response = await fetch('/admin/upload_status');
        if (response.ok) {
            window.location.replace('/');
        }
    } catch (error) {
        // not logged in
    }
}