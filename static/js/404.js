let countdown = 10;
const redirectTimer = setTimeout(() => {
    window.location.href = '/';
}, 10000);

document.addEventListener('click', () => {
    clearTimeout(redirectTimer);
});

document.addEventListener('keydown', () => {
    clearTimeout(redirectTimer);
});