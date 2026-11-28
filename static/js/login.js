/*
 * login.js - the login page (5.48: async, no page refresh).
 *
 * The form is submitted with JSON; success hands over to the page shell, which swaps the file
 * manager into this same document (static/js/shell.js). Errors and the lockout countdown are shown
 * in place. Without JavaScript the form still posts the classic way and the server answers with a
 * redirect or a rendered page.
 *
 * Every network call here asks for redirect: 'manual' (tests/unit/test_login_js.py): an anonymous
 * request to a protected URL is answered with a redirect to /login, which a default call would
 * follow and report as ok.
 *
 * Elements it depends on (templates/login.html): loginForm, loginBtn, username, password,
 * flashText (inside .flash-messages) and .form-control.
 */
(function () {
    'use strict';

    var shell = window.CloudinatorShell || null;
    var life = shell ? shell.createLifecycle('login') : null;

    function listen(target, type, handler, options) {
        if (life) {
            life.listen(target, type, handler, options);
        } else {
            target.addEventListener(type, handler, options);
        }
    }

    var timers = life ? life.globals : {
        setTimeout: window.setTimeout.bind(window),
        clearTimeout: window.clearTimeout.bind(window),
        setInterval: window.setInterval.bind(window),
        clearInterval: window.clearInterval.bind(window),
        fetch: window.fetch.bind(window)
    };
    var fetch = timers.fetch;

    var form = document.getElementById('loginForm');
    var button = document.getElementById('loginBtn');
    var usernameInput = document.getElementById('username');
    var passwordInput = document.getElementById('password');
    if (!form || !button || !usernameInput || !passwordInput) {
        return;
    }

    var idleLabel = button.textContent.trim() || 'Sign In';
    var busy = false;
    var countdown = null;
    // Run after the page finished loading means this script was put in place by the shell
    // (after a logout or an expired session), not parsed with the page.
    var mountedInPage = document.readyState !== 'loading';

    // ------------------------------------------------------------------------------- messages
    function flashBox() {
        var text = document.getElementById('flashText');
        if (text) {
            return text;
        }
        var wrap = document.querySelector('.flash-messages');
        if (!wrap) {
            wrap = document.createElement('div');
            wrap.className = 'flash-messages';
            form.parentNode.insertBefore(wrap, form.nextSibling);
        }
        var msg = document.createElement('div');
        msg.className = 'flash-message';
        msg.id = 'flashMsg';
        var icon = document.createElement('i');
        icon.className = 'fas fa-exclamation-triangle';
        text = document.createElement('span');
        text.id = 'flashText';
        msg.appendChild(icon);
        msg.appendChild(text);
        wrap.appendChild(msg);
        return text;
    }

    function showMessage(message) {
        flashBox().textContent = message;
    }

    function setLoading(on) {
        busy = on;
        button.classList.toggle('loading', on);
        button.textContent = on ? 'Signing In...' : idleLabel;
        button.disabled = on;
    }

    function setInputsDisabled(disabled) {
        Array.prototype.forEach.call(form.querySelectorAll('input'), function (input) {
            input.disabled = disabled;
        });
        button.disabled = disabled;
    }

    // The lockout countdown. The wording is the server's ("Try again in N seconds"), only the
    // number is replaced every second.
    function startCountdown(seconds, template) {
        if (countdown !== null) {
            timers.clearInterval(countdown);
        }
        var left = seconds;
        setInputsDisabled(true);
        showMessage(template.replace(/\d+ seconds/, left + ' seconds'));
        countdown = timers.setInterval(function () {
            left -= 1;
            if (left <= 0) {
                timers.clearInterval(countdown);
                countdown = null;
                showMessage('Lockout expired. You may try again.');
                setInputsDisabled(false);
                usernameInput.focus();
            } else {
                showMessage(template.replace(/\d+ seconds/, left + ' seconds'));
            }
        }, 1000);
    }

    // ------------------------------------------------------------------------------- network
    function currentToken() {
        var token = shell ? shell.csrfToken() : null;
        if (token) {
            return token;
        }
        var field = form.elements.csrf_token;
        return field ? field.value : '';
    }

    function storeToken(token) {
        if (!token) {
            return;
        }
        if (shell) {
            shell.setCsrfToken(token);
        }
        var field = form.elements.csrf_token;
        if (field) {
            field.value = token;
        }
    }

    function refreshToken() {
        return fetch('/csrf-token', {
            credentials: 'same-origin',
            cache: 'no-store',
            redirect: 'manual'
        }).then(function (response) {
            return response.ok ? response.json() : null;
        }).then(function (data) {
            if (data && data.csrf_token) {
                storeToken(data.csrf_token);
                return data.csrf_token;
            }
            return null;
        }).catch(function () {
            return null;
        });
    }

    function sendLogin(token) {
        return fetch('/login', {
            method: 'POST',
            credentials: 'same-origin',
            cache: 'no-store',
            redirect: 'manual',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': token || ''
            },
            body: JSON.stringify({
                username: usernameInput.value.trim(),
                password: passwordInput.value
            })
        });
    }

    function goToApp() {
        if (shell) {
            return shell.toApp();
        }
        window.location.replace('/');
        return Promise.resolve(false);
    }

    async function submitLogin() {
        if (busy || countdown !== null) {
            return;
        }
        setLoading(true);
        try {
            var response = await sendLogin(currentToken());
            if (response.status === 400) {
                // The token on this page is stale (the session changed since it was rendered):
                // take the current one and send the same login once more.
                var fresh = await refreshToken();
                if (fresh) {
                    response = await sendLogin(fresh);
                }
            }

            var data = null;
            try {
                data = await response.json();
            } catch (e) {
                data = null;
            }

            if (response.ok && data && data.success) {
                storeToken(data.csrf_token);
                await goToApp();
                return;
            }

            setLoading(false);
            passwordInput.value = '';
            if (response.status === 429 && data && data.retry_after) {
                startCountdown(Number(data.retry_after), data.message || 'Too many failed attempts. Try again in 0 seconds.');
            } else if (data && data.message) {
                showMessage(data.message);
                passwordInput.focus();
            } else if (response.status === 400) {
                showMessage('This page is out of date. Please reload it and try again.');
            } else {
                showMessage('Could not sign in right now. Please try again.');
            }
        } catch (error) {
            setLoading(false);
            showMessage('Could not reach the server. Check your connection and try again.');
        }
    }

    // ------------------------------------------------------------------------- session probes
    async function checkAuthenticationStatus() {
        try {
            // redirect: 'manual' stops the browser from following the redirect to /login, so an
            // anonymous visitor does not trigger a second request just for this check.
            var response = await fetch('/', {
                method: 'GET',
                cache: 'no-cache',
                redirect: 'manual',
                headers: { 'Cache-Control': 'no-cache' }
            });

            if (response.type === 'opaqueredirect' || response.url.includes('/login')) {
                return;
            }

            if (response.ok) {
                // Only the status was needed; don't download the whole file manager page.
                if (response.body) {
                    response.body.cancel();
                }
                goToApp();
            }
        } catch (error) {
            // not logged in
        }
    }

    async function checkAndRedirectIfLoggedIn() {
        try {
            // redirect: 'manual': a logged-out visitor is answered with a redirect to /login. A
            // followed redirect would report the login page itself as ok, and this page would
            // replace itself with '/' (which redirects back here) and wipe what was typed.
            var response = await fetch('/admin/upload_status', { redirect: 'manual' });
            if (response.ok) {
                // Only the status was needed; don't download the whole answer.
                if (response.body) {
                    response.body.cancel();
                }
                goToApp();
            }
        } catch (error) {
            // not logged in
        }
    }

    // ------------------------------------------------------------------------------- start up
    listen(form, 'submit', function (event) {
        event.preventDefault();
        submitLogin();
    });

    Array.prototype.forEach.call(document.querySelectorAll('.form-control'), function (input) {
        listen(input, 'focus', function () {
            this.parentElement.style.transform = 'scale(1.02)';
        });
        listen(input, 'blur', function () {
            this.parentElement.style.transform = 'scale(1)';
        });
    });

    listen(document, 'visibilitychange', function () {
        if (!document.hidden) {
            checkAndRedirectIfLoggedIn();
        }
    });

    // The classic flow (no JavaScript, or a login that came back as a page) shows the lockout as
    // a flash message: run the same countdown on it.
    (function () {
        var flashText = document.getElementById('flashText');
        if (!flashText) {
            return;
        }
        var message = flashText.textContent;
        var match = message.match(/Try again in (\d+) seconds/);
        if (match) {
            startCountdown(parseInt(match[1], 10), message);
        }
    })();

    var notice = shell ? shell.takeNotice() : null;
    if (notice) {
        showMessage(notice);
    }

    if (mountedInPage) {
        usernameInput.focus();
    } else {
        var params = new URLSearchParams(window.location.search);
        if (params.has('logged_out')) {
            window.history.replaceState({}, document.title, window.location.pathname);
        } else if (!(document.referrer || '').includes('/logout')) {
            checkAuthenticationStatus();
        }
    }

    if (shell) {
        shell.registerPage({
            name: 'login',
            stats: function () { return life.stats(); },
            dispose: function () {
                if (countdown !== null) {
                    timers.clearInterval(countdown);
                    countdown = null;
                }
                return life.dispose();
            }
        });
    }
})();
