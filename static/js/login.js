// Check if user is already logged in and handle browser history
document.addEventListener('DOMContentLoaded', function() {
    // If we have a logged_out parameter, clean up the URL
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.has('logged_out')) {
        // Clean up the URL to remove the logout parameter
        window.history.replaceState({}, document.title, window.location.pathname);
        return; // Don't check authentication status after logout
    }
    
    // Only check authentication status if we're not coming from a logout
    // Check URL parameters and referrer to avoid loops
    if (!isComingFromLogout()) {
        checkAuthenticationStatus();
    }
});

function isComingFromLogout() {
    // Check if we have a logout parameter or if we're coming from logout
    const urlParams = new URLSearchParams(window.location.search);
    const referrer = document.referrer;
    
    // If there's a logout parameter or we came from logout route, don't check auth
    if (urlParams.has('logged_out') || referrer.includes('/logout')) {
        return true;
    }
    
    // Also check if this is a fresh login page load (not a redirect)
    if (window.history.length === 1) {
        return false; // This is a direct navigation, safe to check auth
    }
    
    return false;
}

async function checkAuthenticationStatus() {
    try {
        // Use a more specific endpoint that's less likely to have caching issues
        const response = await fetch('/', {
            method: 'GET',
            cache: 'no-cache',
            headers: {
                'Cache-Control': 'no-cache'
            }
        });
        
        // If we get redirected to login, we're not authenticated
        if (response.url.includes('/login')) {
            console.log('User not logged in, staying on login page');
            return;
        }
        
        // If we get a successful response to the main page, we're logged in
        if (response.ok && !response.url.includes('/login')) {
            console.log('User already logged in, redirecting...');
            window.history.replaceState(null, '', '/');
            window.location.replace('/');
        }
    } catch (error) {
        // If fetch fails, user is probably not logged in, which is expected on login page
        console.log('User not logged in, staying on login page');
    }
}

document.getElementById('loginForm').addEventListener('submit', function (e) {
    const btn = document.getElementById('loginBtn');
    btn.classList.add('loading');
    btn.innerHTML = 'Signing In...';
    
    // Add a small delay to ensure the form processes before any redirect
    setTimeout(() => {
        // After successful login, we'll replace the history state to prevent back button issues
        // This will be handled by the backend redirect, but we can prepare for it
    }, 100);
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