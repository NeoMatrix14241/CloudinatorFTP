var e = class {
    #e = new AbortController;
    #t = new Map;
    get base() {
        return this.#e.signal
    }
    clear() {
        for (let e of this.#t.values()) e.abort();
        this.#t.clear()
    }
    reset() {
        this.clear(), this.#e.abort(), this.#e = new AbortController
    }
    supersede(e) {
        this.#t.get(e)?.abort();
        let t = new AbortController;
        return this.#t.set(e, t), AbortSignal.any([this.#e.signal, t.signal])
    }
};

function t(...e) {
    return {
        state: t => {
            let n = e.map(e => e.state(t));
            return Object.assign({}, ...n)
        },
        attach: t => {
            for (let n of e) try {
                n.attach?.(t)
            } catch (e) {
                t.reportError(e)
            }
        }
    }
}
var n = class extends Error {
    code;
    cause;
    constructor(e, t) {
        super(t?.message ?? e), this.name = `StoreError`, this.code = e, this.cause = t?.cause
    }
};

function r() {
    throw new n(`NO_TARGET`)
}

function i() {
    throw new n(`DESTROYED`)
}

function a(e) {
    return typeof e == `number`
}

function o(e) {
    return typeof e == `function`
}

function s(e) {
    return e === null
}

function c(e) {
    return e === void 0
}

function l(e) {
    return typeof e == `object` && !!e
}

function u(e, t) {
    let n = {
        ...t
    };
    for (let t in e) c(e[t]) || (n[t] = e[t]);
    return n
}

function d(e, t) {
    let n = {};
    for (let r of t) n[r] = e[r];
    return n
}
const f = {
    target: r,
    signals: new e,
    set: r
};

function p(e) {
    let t = e.state(f),
        n = Object.keys(t),
        r = n[0];
    return r ? Object.assign(e => {
        if (r in e) return d(e, n)
    }, {
        displayName: e.name
    }) : Object.assign(() => void 0, {
        displayName: e.name
    })
}
const m = Object.prototype.hasOwnProperty;

function h(e, t) {
    if (Object.is(e, t)) return !0;
    if (typeof e != `object` || !e || typeof t != `object` || !t) return !1;
    let n = Object.keys(e),
        r = Object.keys(t);
    if (n.length !== r.length) return !1;
    for (let r of n)
        if (!m.call(t, r) || !Object.is(e[r], t[r])) return !1;
    return !0
}

function g() {
    return e => e
}

function _(...e) {}

function v(e, t) {
    let n = null,
        r, i = (...i) => {
            r = i, n === null && (n = setTimeout(() => {
                n = null, e(...r)
            }, t))
        };
    return i.cancel = () => {
        n !== null && (clearTimeout(n), n = null)
    }, i
}
let y = !1;

function ee() {
    y || (y = !0, queueMicrotask(ne))
}
const te = new Set;

function ne() {
    y = !1;
    for (let e of te) e.flush();
    te.clear()
}
const re = Object.prototype.hasOwnProperty;
var ie = class {
    #e;
    #t = new Set;
    #n = !1;
    constructor(e) {
        this.#e = Object.freeze({
            ...e
        })
    }
    get current() {
        return this.#e
    }
    patch(e) {
        let t = {
                ...this.#e
            },
            n = !1;
        for (let r in e) {
            if (!re.call(e, r)) continue;
            let i = e[r];
            Object.is(this.#e[r], i) || (t[r] = i, n = !0)
        }
        n && (this.#e = Object.freeze(t), this.#r())
    }
    subscribe(e, t) {
        let n = t?.signal;
        if (n?.aborted) return _;
        if (this.#t.add(e), !n) return () => this.#t.delete(e);
        let r = () => this.#t.delete(e);
        return n.addEventListener(`abort`, r, {
            once: !0
        }), () => {
            n.removeEventListener(`abort`, r), this.#t.delete(e)
        }
    }
    flush() {
        if (this.#n) {
            this.#n = !1;
            for (let e of this.#t) e()
        }
    }
    #r() {
        this.#n = !0, te.add(this), ee()
    }
};

function b(e) {
    return new ie(e)
}
const ae = Symbol(`@videojs/store`);

function oe() {
    return (t, n = {}) => {
        let a = null,
            o = !1,
            c = new AbortController,
            l = new e,
            u;

        function d() {
            o && i(), a || r()
        }
        let f = t.state({
            target: () => (d(), a),
            signals: l,
            set: e => u.patch(e)
        });
        u = b(f);
        let p = {
            [ae]: !0,
            get $state() {
                return u
            },
            get target() {
                return a
            },
            get destroyed() {
                return o
            },
            get state() {
                return u.current
            },
            attach: m,
            destroy: g,
            subscribe: _
        };
        for (let e of Object.keys(f)) Object.defineProperty(p, e, {
            get: () => u.current[e],
            enumerable: !0
        });
        try {
            n.onSetup?.({
                store: p,
                signal: c.signal
            })
        } catch (e) {
            v(e)
        }
        return p;

        function m(e) {
            o && i(), l.reset(), a = e;
            let r = {
                target: e,
                signal: l.base,
                get: () => u.current,
                set: e => u.patch(e),
                reportError: v,
                store: {
                    get state() {
                        return u.current
                    },
                    subscribe: _
                }
            };
            try {
                t.attach?.(r)
            } catch (e) {
                v(e)
            }
            try {
                n.onAttach?.({
                    store: p,
                    target: e,
                    signal: l.base
                })
            } catch (e) {
                v(e)
            }
            return h
        }

        function h() {
            s(a) || (l.reset(), a = null, u.patch(f))
        }

        function g() {
            o || (o = !0, h(), c.abort())
        }

        function _(e, t) {
            return u.subscribe(e, t)
        }

        function v(e) {
            n.onError ? n.onError({
                store: p,
                error: e
            }) : console.error(`[vjs-store]`, e)
        }
    }
}

function se(e) {
    return l(e) && ae in e
}
const x = g();

function ce(e) {
    let t = e.closest(`[dir]`)?.getAttribute(`dir`);
    return t ? t.toLowerCase() === `rtl` : getComputedStyle(e).direction === `rtl`
}

function le(e, t, n) {
    return new Promise((r, i) => {
        let a = () => {
            i(n?.signal?.reason ?? `Aborted`)
        };
        if (n?.signal?.aborted) {
            a();
            return
        }
        n?.signal?.addEventListener(`abort`, a, {
            once: !0
        }), e.addEventListener(t, e => {
            n?.signal?.removeEventListener(`abort`, a), r(e)
        }, {
            ...n,
            once: !0
        })
    })
}

function S() {
    return typeof CSS < `u` && CSS.supports(`anchor-name: --a`)
}

function C(e, t, n, r) {
    return e.addEventListener(t, n, r), () => e.removeEventListener(t, n, r)
}

function ue(e) {
    try {
        e?.showPopover?.()
    } catch {}
}

function w(e) {
    try {
        e?.hidePopover?.()
    } catch {}
}

function de(e) {
    return e.replace(/[A-Z]/g, e => `-${e.toLowerCase()}`)
}

function T(e, t) {
    for (let [n, r] of Object.entries(t))
        if (typeof r == `string`) {
            let t = n.startsWith(`--`) ? n : de(n);
            e.style.setProperty(t, r)
        }
}

function fe(e, t) {
    for (let n of e.querySelectorAll(`track`))
        if (n.track === t) return n;
    return null
}

function pe(e, t) {
    return e?.textTracks ? Array.from(e.textTracks).filter(t).sort(me) : []
}

function me(e, t) {
    return e.kind >= t.kind ? 1 : -1
}

function he(e) {
    let t = [];
    for (let n = 0; n < e.length; n++) t.push([e.start(n), e.end(n)]);
    return t
}
const ge = x({
        name: `buffer`,
        state: () => ({
            buffered: [],
            seekable: []
        }),
        attach({
            target: e,
            signal: t,
            set: n
        }) {
            let {
                media: r
            } = e, i = () => n({
                buffered: he(r.buffered),
                seekable: he(r.seekable)
            });
            i(), C(r, `progress`, i, {
                signal: t
            }), C(r, `emptied`, i, {
                signal: t
            })
        }
    }),
    _e = x({
        name: `controls`,
        state: () => ({
            userActive: !0,
            controlsVisible: !0
        }),
        attach({
            target: e,
            signal: t,
            get: n,
            set: r
        }) {
            let {
                media: i,
                container: a
            } = e;
            if (s(a)) return;

            function o(e) {
                return e || i.paused
            }
            let c;

            function l() {
                clearTimeout(c), c = void 0
            }

            function u() {
                l(), c = setTimeout(f, 2e3)
            }

            function d() {
                n().userActive || r({
                    userActive: !0,
                    controlsVisible: !0
                }), u()
            }

            function f() {
                l(), r({
                    userActive: !1,
                    controlsVisible: o(!1)
                })
            }
            let p = 0;

            function m() {
                p = Date.now()
            }

            function h(e) {
                if (e.pointerType === `touch` && Date.now() - p < 250) {
                    let t = [i, a].includes(e.target);
                    n().controlsVisible && t ? f() : d()
                } else d()
            }

            function g() {
                let {
                    userActive: e
                } = n();
                r({
                    controlsVisible: o(e)
                }), !i.paused && e && u()
            }
            C(a, `pointermove`, d, {
                signal: t
            }), C(a, `pointerdown`, m, {
                signal: t
            }), C(a, `pointerup`, h, {
                signal: t
            }), C(a, `keyup`, d, {
                signal: t
            }), C(a, `focusin`, d, {
                signal: t
            }), C(a, `mouseleave`, f, {
                signal: t
            }), C(i, `play`, g, {
                signal: t
            }), C(i, `pause`, g, {
                signal: t
            }), C(i, `ended`, g, {
                signal: t
            }), t.addEventListener(`abort`, l, {
                once: !0
            }), u()
        }
    }),
    ve = x({
        name: `error`,
        state: ({
            set: e
        }) => ({
            error: null,
            dismissError() {
                e({
                    error: null
                })
            }
        }),
        attach({
            target: e,
            signal: t,
            set: n
        }) {
            let {
                media: r
            } = e;
            C(r, `error`, () => n({
                error: r.error
            }), {
                signal: t
            }), C(r, `emptied`, () => n({
                error: null
            }), {
                signal: t
            })
        }
    });

function ye() {
    let e = document;
    return e.fullscreenEnabled || e.webkitFullscreenEnabled ? !0 : document.createElement(`video`).webkitSupportsFullscreen === !0
}

function be() {
    let e = document;
    return e.fullscreenElement ?? e.webkitFullscreenElement ?? null
}

function xe(e, t) {
    let n = t;
    if (n.webkitDisplayingFullscreen && n.webkitPresentationMode === `fullscreen`) return !0;
    let r = e ?? t;
    if (be() === r) return !0;
    try {
        return r.matches(`:fullscreen`)
    } catch {
        return !1
    }
}
async function Se(e, t) {
    let n = t;
    if (e) {
        let t = e;
        if (o(t.requestFullscreen)) return t.requestFullscreen();
        if (o(t.webkitRequestFullscreen)) return t.webkitRequestFullscreen();
        if (o(t.webkitRequestFullScreen)) return t.webkitRequestFullScreen()
    }
    if (o(n.webkitEnterFullscreen)) {
        n.webkitEnterFullscreen();
        return
    }
    if (o(t.requestFullscreen)) return t.requestFullscreen();
    throw new DOMException(`Fullscreen not supported`, `NotSupportedError`)
}
async function Ce() {
    let e = document,
        t = be();
    if (o(e.exitFullscreen)) return e.exitFullscreen();
    if (o(e.webkitExitFullscreen)) return e.webkitExitFullscreen();
    if (o(e.webkitCancelFullScreen)) return e.webkitCancelFullScreen();
    if (t && o(t.webkitExitFullscreen)) {
        t.webkitExitFullscreen();
        return
    }
}

function we(e) {
    let t = e.target;
    return t instanceof HTMLMediaElement ? t : e
}

function Te() {
    if (document.pictureInPictureEnabled) {
        let e = /.*Version\/.*Safari\/.*/.test(navigator.userAgent),
            t = typeof matchMedia == `function` && matchMedia(`(display-mode: standalone)`).matches;
        return !e || !t
    }
    return o(document.createElement(`video`).webkitSetPresentationMode)
}

function Ee(e) {
    let t = we(e);
    return document.pictureInPictureElement === t ? !0 : t.webkitPresentationMode === `picture-in-picture`
}
async function De(e) {
    let t = we(e);
    if (o(t.requestPictureInPicture)) {
        await t.requestPictureInPicture();
        return
    }
    if (o(t.webkitSetPresentationMode)) {
        t.webkitSetPresentationMode(`picture-in-picture`);
        return
    }
    throw new DOMException(`Picture-in-Picture not supported`, `NotSupportedError`)
}
async function Oe(e) {
    if (o(document.exitPictureInPicture)) try {
        await document.exitPictureInPicture();
        return
    } catch {}
    if (e) {
        let t = we(e),
            n = t.webkitPresentationMode;
        if (o(t.webkitSetPresentationMode) && (!n || n === `picture-in-picture`)) {
            t.webkitSetPresentationMode(`inline`);
            return
        }
    }
}
const ke = x({
        name: `fullscreen`,
        state: ({
            target: e
        }) => ({
            fullscreen: !1,
            fullscreenAvailability: `unavailable`,
            async requestFullscreen() {
                let {
                    media: t,
                    container: n
                } = e();
                return Ee(t) && await Oe(t), Se(n, t)
            },
            async exitFullscreen() {
                return Ce()
            }
        }),
        attach({
            target: e,
            signal: t,
            set: n
        }) {
            let {
                media: r,
                container: i
            } = e;
            n({
                fullscreenAvailability: ye() ? `available` : `unsupported`
            });
            let a = () => n({
                fullscreen: xe(i, r)
            });
            a(), C(document, `fullscreenchange`, a, {
                signal: t
            }), C(document, `webkitfullscreenchange`, a, {
                signal: t
            }), `webkitPresentationMode` in r && C(r, `webkitpresentationmodechanged`, a, {
                signal: t
            })
        }
    }),
    Ae = x({
        name: `pip`,
        state: ({
            target: e
        }) => ({
            pip: !1,
            pipAvailability: `unavailable`,
            async requestPictureInPicture() {
                let {
                    media: t,
                    container: n
                } = e();
                return xe(n, t) && await Ce(), De(t)
            },
            async exitPictureInPicture() {
                let {
                    media: t
                } = e();
                return Oe(t)
            }
        }),
        attach({
            target: e,
            signal: t,
            set: n
        }) {
            let {
                media: r
            } = e;
            n({
                pipAvailability: Te() ? `available` : `unsupported`
            });
            let i = () => n({
                pip: Ee(r)
            });
            i(), C(r, `enterpictureinpicture`, i, {
                signal: t
            }), C(r, `leavepictureinpicture`, i, {
                signal: t
            }), `webkitPresentationMode` in r && C(r, `webkitpresentationmodechanged`, i, {
                signal: t
            })
        }
    }),
    je = x({
        name: `playback`,
        state: ({
            target: e
        }) => ({
            paused: !0,
            ended: !1,
            started: !1,
            waiting: !1,
            play() {
                return e().media.play()
            },
            pause() {
                e().media.pause()
            }
        }),
        attach({
            target: e,
            signal: t,
            set: n
        }) {
            let {
                media: r
            } = e, i = () => n({
                paused: r.paused,
                ended: r.ended,
                started: !r.paused || r.currentTime > 0,
                waiting: r.readyState < HTMLMediaElement.HAVE_FUTURE_DATA && !r.paused
            });
            i(), C(r, `emptied`, i, {
                signal: t
            }), C(r, `play`, i, {
                signal: t
            }), C(r, `pause`, i, {
                signal: t
            }), C(r, `ended`, i, {
                signal: t
            }), C(r, `playing`, i, {
                signal: t
            }), C(r, `waiting`, i, {
                signal: t
            })
        }
    }),
    Me = [1, 1.2, 1.5, 1.7, 2],
    Ne = x({
        name: `playbackRate`,
        state: ({
            target: e
        }) => ({
            playbackRates: Me,
            playbackRate: 1,
            setPlaybackRate(t) {
                e().media.playbackRate = t
            }
        }),
        attach({
            target: e,
            signal: t,
            set: n
        }) {
            let {
                media: r
            } = e, i = () => n({
                playbackRate: r.playbackRate
            });
            i(), C(r, `ratechange`, i, {
                signal: t
            })
        }
    }),
    Pe = x({
        name: `source`,
        state: ({
            target: e,
            signals: t
        }) => ({
            source: null,
            canPlay: !1,
            loadSource(n) {
                t.clear();
                let {
                    media: r
                } = e();
                return r.src = n, r.load(), n
            }
        }),
        attach({
            target: e,
            signal: t,
            set: n
        }) {
            let {
                media: r
            } = e, i = () => n({
                source: r.currentSrc || r.src || null,
                canPlay: r.readyState >= HTMLMediaElement.HAVE_ENOUGH_DATA
            });
            i(), C(r, `canplay`, i, {
                signal: t
            }), C(r, `canplaythrough`, i, {
                signal: t
            }), C(r, `loadstart`, i, {
                signal: t
            }), C(r, `emptied`, i, {
                signal: t
            })
        }
    }),
    Fe = x({
        name: `textTrack`,
        state: ({
            target: e
        }) => ({
            chaptersCues: [],
            thumbnailCues: [],
            thumbnailTrackSrc: null,
            textTrackList: [],
            subtitlesShowing: !1,
            toggleSubtitles(t) {
                let n = pe(e().media, e => e.kind === `subtitles` || e.kind === `captions`);
                if (!n.length) return !1;
                let r = n.some(e => e.mode === `showing`),
                    i = t ?? !r;
                for (let e of n) e.mode = i ? `showing` : `disabled`;
                return i
            }
        }),
        attach({
            target: e,
            signal: t,
            set: n
        }) {
            let {
                media: r
            } = e, i = null;

            function a() {
                i?.abort(), i = new AbortController;
                let e = null,
                    t = null,
                    o = [],
                    s = !1;
                for (let n = 0; n < r.textTracks.length; n++) {
                    let i = r.textTracks[n];
                    !e && i.kind === `chapters` && (e = i), !t && i.kind === `metadata` && i.label === `thumbnails` && (t = i), o.push({
                        kind: i.kind,
                        label: i.label,
                        language: i.language,
                        mode: i.mode
                    }), (i.kind === `captions` || i.kind === `subtitles`) && i.mode === `showing` && (s = !0)
                }
                let c = e?.cues ? Array.from(e.cues) : [],
                    l = t?.cues ? Array.from(t.cues) : [],
                    u = null;
                t && (u = fe(r, t)?.src ?? null);
                for (let e of r.querySelectorAll?.(`track`) ?? []) e.track?.cues?.length || C(e, `load`, a, {
                    signal: i.signal
                });
                n({
                    chaptersCues: c,
                    thumbnailCues: l,
                    thumbnailTrackSrc: u,
                    textTrackList: o,
                    subtitlesShowing: s
                })
            }
            a(), C(r.textTracks, `addtrack`, a, {
                signal: t
            }), C(r.textTracks, `removetrack`, a, {
                signal: t
            }), C(r.textTracks, `change`, a, {
                signal: t
            }), C(r, `loadstart`, a, {
                signal: t
            }), t.addEventListener(`abort`, () => i?.abort(), {
                once: !0
            })
        }
    });

function Ie(e) {
    return e.readyState >= HTMLMediaElement.HAVE_METADATA
}
const Le = {
        seek: Symbol.for(`@videojs/seek`)
    },
    Re = x({
        name: `time`,
        state: ({
            target: e,
            signals: t,
            set: n
        }) => ({
            currentTime: 0,
            duration: 0,
            seeking: !1,
            async seek(r) {
                let {
                    media: i
                } = e(), a = t.supersede(Le.seek);
                if (!Ie(i) && !await le(i, `loadedmetadata`, {
                        signal: a
                    }).catch(() => !1)) return i.currentTime;
                let o = Math.max(0, Math.min(r, i.duration || 1 / 0));
                return n({
                    currentTime: o,
                    seeking: !0
                }), i.currentTime = o, await le(i, `seeked`, {
                    signal: a
                }).catch(_), i.currentTime
            }
        }),
        attach({
            target: e,
            signal: t,
            set: n
        }) {
            let {
                media: r
            } = e, i = () => n({
                currentTime: r.currentTime,
                duration: Number.isFinite(r.duration) ? r.duration : 0,
                seeking: r.seeking
            });
            i(), C(r, `timeupdate`, i, {
                signal: t
            }), C(r, `durationchange`, i, {
                signal: t
            }), C(r, `seeking`, i, {
                signal: t
            }), C(r, `seeked`, i, {
                signal: t
            }), C(r, `loadedmetadata`, i, {
                signal: t
            }), C(r, `emptied`, i, {
                signal: t
            })
        }
    }),
    ze = x({
        name: `volume`,
        state: ({
            target: e
        }) => ({
            volume: 1,
            muted: !1,
            volumeAvailability: `unavailable`,
            setVolume(t) {
                let {
                    media: n
                } = e(), r = Math.max(0, Math.min(1, t));
                return r > 0 && n.muted && (n.muted = !1), n.volume = r, n.volume
            },
            toggleMuted() {
                let {
                    media: t
                } = e();
                return t.muted || t.volume === 0 ? (t.muted = !1, t.volume === 0 && (t.volume = .25)) : t.muted = !0, t.muted
            }
        }),
        attach({
            target: e,
            signal: t,
            set: n
        }) {
            let {
                media: r
            } = e;
            n({
                volumeAvailability: Be()
            });
            let i = () => n({
                volume: r.volume,
                muted: r.muted
            });
            i(), C(r, `volumechange`, i, {
                signal: t
            })
        }
    });

function Be() {
    let e = document.createElement(`video`);
    try {
        return e.volume = .5, e.volume === .5 ? `available` : `unsupported`
    } catch {
        return `unsupported`
    }
}
const Ve = [je, Ne, ze, Re, Pe, ge, ke, Ae, _e, Fe, ve],
    He = p(ge),
    Ue = p(_e);
p(ve);
const We = p(ke),
    Ge = p(Ae),
    Ke = p(je),
    qe = p(Ne);
p(Pe);
const Je = p(Fe),
    Ye = p(Re),
    Xe = p(ze);

function Ze(e) {
    let {
        transition: t
    } = e, n = t.state, r = new AbortController, i = null;

    function a() {
        if (r.signal.aborted) return null;
        let {
            active: e,
            status: i
        } = n.current;
        return e && i !== `ending` ? null : (i === `ending` && t.cancel(), t.open())
    }

    function o(e) {
        let {
            active: i,
            status: a
        } = n.current;
        return r.signal.aborted || !i || a === `ending` ? null : t.close(e)
    }

    function s() {
        if (c(), typeof document > `u`) return;
        i = new AbortController;
        let {
            signal: t
        } = i;
        C(document, `keydown`, l, {
            signal: t
        }), e.onDocumentActive?.(t)
    }

    function c() {
        i?.abort(), i = null
    }

    function l(t) {
        t.key === `Escape` && n.current.active && (e.closeOnEscape?.() ?? !0) && e.onEscapeDismiss(t)
    }
    let u = n.subscribe(() => {
        n.current.active ? s() : c()
    });
    r.signal.addEventListener(`abort`, () => {
        u(), t.destroy(), c()
    });

    function d() {
        r.signal.aborted || r.abort()
    }
    return {
        input: n,
        open: a,
        close: o,
        signal: r.signal,
        destroy: d
    }
}

function Qe(e) {
    let {
        onActivate: t,
        isDisabled: n
    } = e;
    return {
        role: `button`,
        tabIndex: 0,
        onClick(e) {
            if (n()) {
                e.preventDefault();
                return
            }
            t()
        },
        onPointerDown(e) {
            n() && e.preventDefault()
        },
        onMouseDown(e) {
            n() && e.preventDefault()
        },
        onKeyDown(e) {
            if (e.target === e.currentTarget) {
                if (n()) {
                    e.key !== `Tab` && e.preventDefault();
                    return
                }
                e.key === `Enter` ? (e.preventDefault(), t()) : e.key === ` ` && e.preventDefault()
            }
        },
        onKeyUp(e) {
            e.target === e.currentTarget && (n() || e.key === ` ` && t())
        }
    }
}

function $e(e) {
    let {
        onOpenChange: t,
        closeOnOutsideClick: n
    } = e, r = null, i = null, a = null, o = new Set, s = Ze({
        transition: e.transition,
        closeOnEscape: e.closeOnEscape,
        onEscapeDismiss(e) {
            e.preventDefault(), f(`escape`, e)
        },
        onDocumentActive(e) {
            C(document, `pointerdown`, h, {
                capture: !0,
                signal: e
            })
        }
    }), c = s.input;

    function l() {
        a !== null && (clearTimeout(a), a = null)
    }

    function u() {
        return globalThis.matchMedia?.(`(hover: hover)`)?.matches ?? !1
    }

    function d(n, r) {
        let i = s.open();
        i && (t(!0, r ? {
            reason: n,
            event: r
        } : {
            reason: n
        }), i.then(() => {
            s.signal.aborted || !c.current.active || e.onOpenChangeComplete?.(!0)
        }))
    }

    function f(n, r) {
        let a = s.close(i);
        a && (t(!1, r ? {
            reason: n,
            event: r
        } : {
            reason: n
        }), a.then(() => {
            s.signal.aborted || (w(i), e.onOpenChangeComplete?.(!1))
        }))
    }

    function p(e = `click`) {
        d(e)
    }

    function m(e = `click`) {
        f(e)
    }

    function h(e) {
        if (!n() || !c.current.active) return;
        let t = e.composedPath();
        r && t.includes(r) || i && t.includes(i) || f(`outside-click`, e)
    }
    s.signal.addEventListener(`abort`, () => {
        l(), o.clear(), r = null, i = null
    });
    let g = {
            onClick(e) {
                c.current.active && c.current.status !== `ending` ? f(`click`, e) : d(`click`, e)
            },
            onPointerEnter(t) {
                if (!e.openOnHover?.() || !u() || (l(), c.current.active)) return;
                let n = e.delay?.() ?? 300;
                a = setTimeout(() => d(`hover`), n)
            },
            onPointerLeave(t) {
                if (!e.openOnHover?.() || !u() || (l(), !c.current.active)) return;
                let n = e.closeDelay?.() ?? 0;
                a = setTimeout(() => f(`hover`), n)
            },
            onFocusIn(t) {
                e.openOnHover?.() && d(`focus`)
            },
            onFocusOut(t) {
                let n = t.relatedTarget;
                n && (r?.contains(n) || i?.contains(n)) || e.openOnHover?.() && f(`blur`)
            }
        },
        _ = {
            onPointerEnter(t) {
                e.openOnHover?.() && l()
            },
            onPointerLeave(t) {
                if (!e.openOnHover?.() || o.size > 0 || (l(), !c.current.active)) return;
                let n = e.closeDelay?.() ?? 0;
                a = setTimeout(() => f(`hover`), n)
            },
            onGotPointerCapture(e) {
                o.add(e.pointerId)
            },
            onLostPointerCapture(e) {
                o.delete(e.pointerId)
            },
            onFocusOut(e) {
                let t = e.relatedTarget;
                t && (r?.contains(t) || i?.contains(t)) || f(`blur`)
            }
        };

    function v(e) {
        r = e
    }

    function y(e) {
        !e && i && c.current.active && w(i), i = e, e && c.current.active && ue(e)
    }
    return {
        input: c,
        triggerProps: g,
        popupProps: _,
        get triggerElement() {
            return r
        },
        setTriggerElement: v,
        setPopupElement: y,
        open: p,
        close: m,
        destroy: s.destroy
    }
}
const E = {
        sideOffset: `--media-popover-side-offset`,
        alignOffset: `--media-popover-align-offset`,
        anchorWidth: `--media-popover-anchor-width`,
        anchorHeight: `--media-popover-anchor-height`,
        availableWidth: `--media-popover-available-width`,
        availableHeight: `--media-popover-available-height`
    },
    et = {
        top: `bottom`,
        bottom: `top`,
        left: `right`,
        right: `left`
    };

function D(e, t, n, r, i, a, o = E) {
    return S() ? nt(e, t, o) : n && r ? {
        ...it(n, r, t, a ?? {
            sideOffset: 0,
            alignOffset: 0
        }),
        ...i ? rt(n, i, t.side, o) : {},
        position: `fixed`,
        inset: `auto`,
        margin: `0`
    } : {}
}

function tt(e) {
    return S() ? {
        anchorName: `--${e}`
    } : {}
}

function nt(e, t, n = E) {
    let r = `var(${n.sideOffset}, 0px)`,
        i = `var(${n.alignOffset}, 0px)`,
        {
            side: a,
            align: o
        } = t,
        s = {
            positionAnchor: `--${e}`,
            position: `fixed`,
            inset: `auto`,
            margin: `0`,
            justifySelf: `normal`,
            alignSelf: `normal`,
            marginInlineStart: `0`,
            marginBlockStart: `0`
        },
        c = et[a];
    return a === `top` || a === `bottom` ? (s[c] = `calc(anchor(${a}) + ${r})`, o === `start` ? s.left = `calc(anchor(left) + ${i})` : o === `end` ? s.right = `calc(anchor(right) + ${i})` : (s.justifySelf = `anchor-center`, s.marginInlineStart = i)) : (s[c] = `calc(anchor(${a}) + ${r})`, o === `start` ? s.top = `calc(anchor(top) + ${i})` : o === `end` ? s.bottom = `calc(anchor(bottom) + ${i})` : (s.alignSelf = `anchor-center`, s.marginBlockStart = i)), s
}

function rt(e, t, n, r = E) {
    let i = {};
    return i[r.anchorWidth] = `${e.width}px`, i[r.anchorHeight] = `${e.height}px`, n === `top` || n === `bottom` ? (i[r.availableHeight] = n === `top` ? `${e.top - t.top}px` : `${t.bottom - e.bottom}px`, i[r.availableWidth] = `${t.width}px`) : (i[r.availableWidth] = n === `left` ? `${e.left - t.left}px` : `${t.right - e.right}px`, i[r.availableHeight] = `${t.height}px`), i
}

function it(e, t, n, r = {
    sideOffset: 0,
    alignOffset: 0
}) {
    let {
        side: i,
        align: a
    } = n, {
        sideOffset: o,
        alignOffset: s
    } = r, c = 0, l = 0;
    return i === `top` ? c = e.top - t.height - o : i === `bottom` ? c = e.bottom + o : l = i === `left` ? e.left - t.width - o : e.right + o, i === `top` || i === `bottom` ? l = a === `start` ? e.left + s : a === `end` ? e.right - t.width + s : e.left + (e.width - t.width) / 2 + s : c = a === `start` ? e.top + s : a === `end` ? e.bottom - t.height + s : e.top + (e.height - t.height) / 2 + s, {
        top: `${c}px`,
        left: `${l}px`
    }
}

function at(e, t = E) {
    let n = getComputedStyle(e);
    return {
        sideOffset: Number.parseFloat(n.getPropertyValue(t.sideOffset)) || 0,
        alignOffset: Number.parseFloat(n.getPropertyValue(t.alignOffset)) || 0
    }
}

function O(e, t, n) {
    return Math.max(t, Math.min(n, e))
}

function ot(e, t, n) {
    let r = Math.round((e - n) / t) * t + n,
        i = `${t}`.indexOf(`.`);
    return i === -1 ? r : Number(r.toFixed(`${t}`.length - i - 1))
}

function k(e, t, n, r) {
    let i;
    return i = n === `vertical` ? 1 - (e.clientY - t.top) / t.height : r ? (t.right - e.clientX) / t.width : (e.clientX - t.left) / t.width, Number.isFinite(i) ? O(i * 100, 0, 100) : 0
}

function st(e) {
    let t = b({
            pointerPercent: 0,
            dragPercent: 0,
            dragging: !1,
            pointing: !1,
            focused: !1
        }),
        n = new AbortController,
        r = e.commitThrottle ?? 0,
        i = !1,
        a = 0,
        o = !1,
        c = null,
        l = null,
        u = r > 0 ? v(t => e.onValueCommit?.(t), r) : null;

    function d() {
        if (s(l)) return;
        let t = l;
        l = null;
        try {
            e.getElement().releasePointerCapture(t)
        } catch {}
    }

    function f() {
        i ? (i = !1, t.patch({
            dragging: !1,
            pointing: !1
        }), e.onDragEnd?.()) : t.patch({
            pointing: !1
        }), p()
    }

    function p() {
        u?.cancel(), l = null, c = null
    }
    let m = {
            onPointerDown(n) {
                if (e.isDisabled()) return;
                n.preventDefault();
                let r = e.getElement();
                c = r.getBoundingClientRect(), o = e.isRTL(), a = 0, d(), l = n.pointerId, r.setPointerCapture(n.pointerId);
                let i = k(n, c, e.getOrientation(), o);
                t.patch({
                    pointing: !0,
                    pointerPercent: i,
                    dragPercent: i
                }), e.onValueChange?.(i), e.getThumbElement?.()?.focus({
                    preventScroll: !0,
                    focusVisible: !1
                })
            },
            onPointerMove(n) {
                if (e.isDisabled()) return;
                if (!s(l)) {
                    if (n.pointerType !== `touch` && n.buttons === 0) {
                        f();
                        return
                    }
                    a++;
                    let r = k(n, c, e.getOrientation(), o);
                    !i && a >= 2 ? (i = !0, t.patch({
                        dragging: !0,
                        dragPercent: r,
                        pointerPercent: r
                    }), e.onDragStart?.(), e.onValueChange?.(r), u?.(r)) : i ? (t.patch({
                        dragPercent: r,
                        pointerPercent: r
                    }), e.onValueChange?.(r), u?.(r)) : t.patch({
                        pointerPercent: r
                    });
                    return
                }
                let r = k(n, e.getElement().getBoundingClientRect(), e.getOrientation(), e.isRTL());
                t.patch({
                    pointing: !0,
                    pointerPercent: r
                })
            },
            onPointerUp(t) {
                if (s(l)) return;
                let n = k(t, c, e.getOrientation(), o);
                u?.cancel(), e.onValueCommit?.(n)
            },
            onPointerLeave() {
                s(l) && t.patch({
                    pointing: !1
                })
            },
            onLostPointerCapture() {
                f()
            }
        },
        h = {
            onKeyDown(n) {
                if (e.isDisabled()) {
                    n.key !== `Tab` && n.preventDefault();
                    return
                }
                let r = e.getStepPercent(),
                    i = e.getLargeStepPercent(),
                    a = ot(e.getPercent(), r, 0),
                    o = e.isRTL() ? -1 : 1,
                    s = n.shiftKey ? i : r,
                    c = null;
                switch (n.key) {
                    case `ArrowRight`:
                        c = a + s * o;
                        break;
                    case `ArrowLeft`:
                        c = a - s * o;
                        break;
                    case `ArrowUp`:
                        c = a + s;
                        break;
                    case `ArrowDown`:
                        c = a - s;
                        break;
                    case `PageUp`:
                        c = a + i;
                        break;
                    case `PageDown`:
                        c = a - i;
                        break;
                    case `Home`:
                        c = 0;
                        break;
                    case `End`:
                        c = 100;
                        break;
                    default:
                        !n.metaKey && !n.ctrlKey && !n.altKey && n.key >= `0` && n.key <= `9` && (c = Number(n.key) * 10);
                        break
                }
                c !== null && (n.preventDefault(), c = O(c, 0, 100), t.patch({
                    pointerPercent: c,
                    dragPercent: c
                }), e.onValueChange?.(c), e.onValueCommit?.(c))
            },
            onFocus() {
                t.patch({
                    focused: !0
                })
            },
            onBlur() {
                t.patch({
                    focused: !1
                })
            }
        };

    function g(t) {
        if (!e.adjustPercent || t.thumbAlignment !== `edge`) return t;
        let n = e.getElement(),
            r = e.getThumbElement?.();
        if (!r) return t;
        let i = t.orientation === `horizontal`,
            a = i ? r.offsetWidth : r.offsetHeight,
            o = i ? n.offsetWidth : n.offsetHeight;
        return {
            ...t,
            fillPercent: e.adjustPercent(t.fillPercent, a, o),
            pointerPercent: e.adjustPercent(t.pointerPercent, a, o)
        }
    }
    let _ = null;
    return e.onResize && (_ = new ResizeObserver(() => e.onResize()), _.observe(e.getElement())), {
        input: t,
        rootProps: m,
        rootStyle: {
            touchAction: `none`,
            userSelect: `none`
        },
        thumbProps: h,
        adjustForAlignment: g,
        destroy() {
            n.signal.aborted || (n.abort(), _?.disconnect(), d(), p())
        }
    }
}
const A = {
    fill: `--media-slider-fill`,
    pointer: `--media-slider-pointer`,
    buffer: `--media-slider-buffer`
};

function ct(e) {
    return {
        [A.fill]: `${e.fillPercent.toFixed(3)}%`,
        [A.pointer]: `${e.pointerPercent.toFixed(3)}%`
    }
}

function lt(e) {
    return {
        ...ct(e),
        [A.buffer]: `${e.bufferPercent.toFixed(3)}%`
    }
}

function ut(e, t) {
    let n = e / 2;
    return {
        position: `absolute`,
        left: t === `visible` ? `calc(var(${A.pointer}) - ${n}px)` : `min(max(0px, calc(var(${A.pointer}) - ${n}px)), calc(100% - ${e}px))`,
        width: `max-content`,
        pointerEvents: `none`
    }
}
var dt = class {
    findActiveThumbnail(e, t) {
        if (e.length === 0) return;
        let n = 0,
            r = e.length - 1,
            i;
        for (; n <= r;) {
            let a = n + r >>> 1,
                o = e[a];
            t >= o.startTime ? (i = o, n = a + 1) : r = a - 1
        }
        return i
    }
    parseConstraints(e) {
        let t = parseFloat(e.minWidth),
            n = parseFloat(e.maxWidth),
            r = parseFloat(e.minHeight),
            i = parseFloat(e.maxHeight);
        return {
            minWidth: Number.isFinite(t) ? t : 0,
            maxWidth: Number.isFinite(n) ? n : 1 / 0,
            minHeight: Number.isFinite(r) ? r : 0,
            maxHeight: Number.isFinite(i) ? i : 1 / 0
        }
    }
    calculateScale(e, t, n) {
        let {
            minWidth: r,
            maxWidth: i,
            minHeight: a,
            maxHeight: o
        } = n, s = Math.min(i / e, o / t), c = Math.max(r / e, a / t);
        return Number.isFinite(s) && s < 1 ? s : Number.isFinite(c) && c > 1 ? c : 1
    }
    resize(e, t, n, r) {
        let i = e.width ?? t,
            a = e.height ?? n;
        if (!i || !a) return;
        let o = this.calculateScale(i, a, r);
        return {
            scale: o,
            containerWidth: i * o,
            containerHeight: a * o,
            imageWidth: t * o,
            imageHeight: n * o,
            offsetX: (e.coords?.x ?? 0) * o,
            offsetY: (e.coords?.y ?? 0) * o
        }
    }
    getState(e, t, n) {
        return {
            loading: e,
            error: t,
            hidden: !e && !n
        }
    }
    getAttrs(e) {
        return {
            role: `img`,
            "aria-hidden": `true`
        }
    }
};

function ft(e) {
    let {
        getContainer: t,
        getImg: n,
        onStateChange: r
    } = e, i = new dt, a = new AbortController, o = a.signal, s = !1, c = !1, l = 0, u = 0, d = ``, f = !1, p = null;

    function m() {
        let e = n();
        e && (l = e.naturalWidth, u = e.naturalHeight), s = !1, c = !1, r()
    }

    function h() {
        s = !1, c = !0, r()
    }

    function g(e) {
        C(e, `load`, m, {
            signal: o
        }), C(e, `error`, h, {
            signal: o
        })
    }

    function _() {
        if (!f) {
            let e = n();
            e && (g(e), f = !0)
        }
        if (!p) {
            let e = t();
            e && (p = new ResizeObserver(r), p.observe(e))
        }
    }

    function v(e) {
        _();
        let t = e ?? ``;
        t !== d && (d = t, t ? (s = !0, c = !1) : (s = !1, c = !1, l = 0, u = 0))
    }

    function y() {
        _();
        let e = n();
        e?.complete && d && (e.naturalWidth > 0 ? (l = e.naturalWidth, u = e.naturalHeight, s = !1, c = !1) : (s = !1, c = !0), r())
    }

    function ee() {
        a.abort(), p?.disconnect(), p = null
    }
    return {
        get loading() {
            return s
        },
        get error() {
            return c
        },
        get naturalWidth() {
            return l
        },
        get naturalHeight() {
            return u
        },
        readConstraints() {
            let e = t();
            return e ? i.parseConstraints(getComputedStyle(e)) : {
                minWidth: 0,
                maxWidth: 1 / 0,
                minHeight: 0,
                maxHeight: 1 / 0
            }
        },
        updateSrc: v,
        connect: y,
        destroy: ee
    }
}
const pt = {
    hover: `hover`,
    focus: `focus`,
    escape: `escape`,
    blur: `blur`
};

function mt(e) {
    let t = {
        transition: e.transition,
        onOpenChange(t, n) {
            let r = pt[n.reason];
            if (!r) return;
            let i = e.group?.();
            t ? i?.notifyOpen() : i?.notifyClose();
            let a = n.event ? {
                reason: r,
                event: n.event
            } : {
                reason: r
            };
            e.onOpenChange(t, a)
        },
        closeOnEscape: () => !0,
        closeOnOutsideClick: () => !1,
        openOnHover: () => !0,
        delay: () => {
            let t = e.group?.();
            return t?.shouldSkipDelay() ? 0 : e.delay?.() ?? t?.delay ?? 600
        },
        closeDelay: () => {
            let t = e.group?.();
            return e.closeDelay?.() ?? t?.closeDelay ?? 0
        }
    };
    e.onOpenChangeComplete && (t.onOpenChangeComplete = e.onOpenChangeComplete);
    let n = $e(t),
        {
            onClick: r,
            ...i
        } = n.triggerProps,
        a = {
            ...i,
            onPointerEnter(t) {
                e.disabled?.() || i.onPointerEnter(t)
            },
            onFocusIn(t) {
                e.disabled?.() || i.onFocusIn(t)
            }
        },
        o = {
            ...n.popupProps,
            onPointerEnter(t) {
                e.disableHoverablePopup?.() || n.popupProps.onPointerEnter(t)
            }
        };
    return {
        ...n,
        triggerProps: a,
        popupProps: o,
        get triggerElement() {
            return n.triggerElement
        },
        open: () => n.open(`hover`),
        close: () => n.close(`hover`)
    }
}

function ht() {
    let e = b({
            active: !1,
            status: `idle`
        }),
        t = !1,
        n = 0,
        r = 0;

    function i() {
        return cancelAnimationFrame(n), cancelAnimationFrame(r), n = 0, r = 0, e.patch({
            active: !0,
            status: `starting`
        }), new Promise(i => {
            n = requestAnimationFrame(() => {
                n = 0, r = requestAnimationFrame(() => {
                    if (r = 0, t || !e.current.active) return i();
                    e.patch({
                        status: `idle`
                    }), i()
                })
            })
        })
    }

    function a(i) {
        return cancelAnimationFrame(n), cancelAnimationFrame(r), n = 0, r = 0, e.patch({
            status: `ending`
        }), new Promise(a => {
            n = requestAnimationFrame(() => {
                n = 0, r = requestAnimationFrame(() => {
                    if (r = 0, t) return a();
                    gt(i).finally(() => {
                        if (t || e.current.status !== `ending`) return a();
                        e.patch({
                            active: !1,
                            status: `idle`
                        }), a()
                    })
                })
            })
        })
    }

    function o() {
        cancelAnimationFrame(n), cancelAnimationFrame(r), n = 0, r = 0, e.current.status !== `idle` && e.patch({
            status: `idle`
        })
    }
    return {
        state: e,
        open: i,
        close: a,
        cancel: o,
        destroy() {
            t || (t = !0, o())
        }
    }
}

function gt(e) {
    if (!e) return Promise.resolve();
    let t = e.getAnimations?.() ?? [];
    return t.length === 0 ? Promise.resolve() : Promise.all(t.map(e => e.finished)).then(_, _)
}

function j(e, t, n) {
    let r = n?.signal;
    for (let [n, i] of Object.entries(t)) o(i) && n.startsWith(`on`) ? C(e, n.slice(2).toLowerCase(), i, r ? {
        signal: r
    } : void 0) : c(i) || i === !1 ? e.removeAttribute(n) : i === !0 ? e.setAttribute(n, ``) : e.setAttribute(n, String(i))
}

function M(e, t, n) {
    for (let r in t) {
        if (n && !(r in n)) continue;
        let i = n?.[r] ?? _t(r),
            a = t[r];
        a === !0 ? e.setAttribute(i, ``) : a ? e.setAttribute(i, String(a)) : e.removeAttribute(i)
    }
}

function _t(e) {
    return `data-${e.toLowerCase()}`
}
/**
 * @license
 * Copyright 2021 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
var vt = class extends Event {
    constructor(e, t, n, r) {
        super(`context-request`, {
            bubbles: !0,
            composed: !0
        }), this.context = e, this.contextTarget = t, this.callback = n, this.subscribe = r ?? !1
    }
};
/**
 * @license
 * Copyright 2021 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
function N(e) {
    return e
}
/**
 * @license
 * Copyright 2021 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
var P = class {
        constructor(e, t, n, r) {
            if (this.subscribe = !1, this.provided = !1, this.value = void 0, this.t = (e, t) => {
                    this.unsubscribe && (this.unsubscribe !== t && (this.provided = !1, this.unsubscribe()), this.subscribe || this.unsubscribe()), this.value = e, this.host.requestUpdate(), this.provided && !this.subscribe || (this.provided = !0, this.callback && this.callback(e, t)), this.unsubscribe = t
                }, this.host = e, t.context !== void 0) {
                let e = t;
                this.context = e.context, this.callback = e.callback, this.subscribe = e.subscribe ?? !1
            } else this.context = t, this.callback = n, this.subscribe = r ?? !1;
            this.host.addController(this)
        }
        hostConnected() {
            this.dispatchRequest()
        }
        hostDisconnected() {
            this.unsubscribe &&= (this.unsubscribe(), void 0)
        }
        dispatchRequest() {
            this.host.dispatchEvent(new vt(this.context, this.host, this.t, this.subscribe))
        }
    },
    yt = class {
        get value() {
            return this.o
        }
        set value(e) {
            this.setValue(e)
        }
        setValue(e, t = !1) {
            let n = t || !Object.is(e, this.o);
            this.o = e, n && this.updateObservers()
        }
        constructor(e) {
            this.subscriptions = new Map, this.updateObservers = () => {
                for (let [e, {
                        disposer: t
                    }] of this.subscriptions) e(this.o, t)
            }, e !== void 0 && (this.value = e)
        }
        addCallback(e, t, n) {
            if (!n) return void e(this.value);
            this.subscriptions.has(e) || this.subscriptions.set(e, {
                disposer: () => {
                    this.subscriptions.delete(e)
                },
                consumerHost: t
            });
            let {
                disposer: r
            } = this.subscriptions.get(e);
            e(this.value, r)
        }
        clearCallbacks() {
            this.subscriptions.clear()
        }
    },
    bt = class extends Event {
        constructor(e, t) {
            super(`context-provider`, {
                bubbles: !0,
                composed: !0
            }), this.context = e, this.contextTarget = t
        }
    },
    F = class extends yt {
        constructor(e, t, n) {
            super(t.context === void 0 ? n : t.initialValue), this.onContextRequest = e => {
                if (e.context !== this.context) return;
                let t = e.contextTarget ?? e.composedPath()[0];
                t !== this.host && (e.stopPropagation(), this.addCallback(e.callback, t, e.subscribe))
            }, this.onProviderRequest = e => {
                if (e.context !== this.context || (e.contextTarget ?? e.composedPath()[0]) === this.host) return;
                let t = new Set;
                for (let [e, {
                        consumerHost: n
                    }] of this.subscriptions) t.has(e) || (t.add(e), n.dispatchEvent(new vt(this.context, n, e, !0)));
                e.stopPropagation()
            }, this.host = e, t.context === void 0 ? this.context = t : this.context = t.context, this.attachListeners(), this.host.addController?.(this)
        }
        attachListeners() {
            this.host.addEventListener(`context-request`, this.onContextRequest), this.host.addEventListener(`context-provider`, this.onProviderRequest)
        }
        hostConnected() {
            this.host.dispatchEvent(new bt(this.context, this.host))
        }
    };
const I = N(Symbol(`@videojs/player`));

function xt(e) {
    return t => {
        class n extends t {
            #e = _;
            #t = null;
            #n = null;
            constructor(...t) {
                super(...t), new P(this, {
                    context: e,
                    callback: e => {
                        this.#n = e ?? null, this.#o()
                    },
                    subscribe: !0
                })
            }
            get store() {
                return this.#n
            }
            connectedCallback() {
                super.connectedCallback(), this.#t = new MutationObserver(e => {
                    e.some(Ct) && this.#o()
                }), this.#t.observe(this, {
                    childList: !0,
                    subtree: !0,
                    attributes: !0,
                    attributeFilter: [`name`]
                }), this.addEventListener(`slotchange`, this.#r), this.#o()
            }
            disconnectedCallback() {
                super.disconnectedCallback(), this.#t?.disconnect(), this.#t = null, this.removeEventListener(`slotchange`, this.#r), this.#e()
            }
            #r = () => {
                this.#o()
            };
            #i() {
                let e = this.querySelector(`slot[name="media"]`);
                if (!e) return null;
                for (let t of e.assignedElements({
                        flatten: !0
                    }))
                    if (L(t)) return t;
                return null
            }
            #a() {
                return Array.from(this.children).find(L) || null
            }
            #o() {
                let e = this.#n ?? this.store;
                if (!e) return;
                let t = this.querySelector(`video, audio`) ?? this.#a() ?? this.#i();
                if (!t) {
                    this.#e(), this.#e = _;
                    return
                }
                St(t) && globalThis.customElements?.upgrade?.(t);
                let n = {
                        media: t,
                        container: this
                    },
                    r = e.target?.media !== n.media,
                    i = e.target?.container !== n.container;
                (r || i) && (this.#e(), this.#e = e.attach(n))
            }
        }
        return n
    }
}

function L(e) {
    return e instanceof HTMLMediaElement || St(e)
}

function St(e) {
    return e instanceof HTMLElement && (e.localName.endsWith(`-audio`) || e.localName.endsWith(`-video`))
}

function R(e) {
    return e instanceof HTMLSlotElement && e.name === `media`
}

function Ct(e) {
    if (R(e.target)) return !0;
    for (let t of e.addedNodes)
        if (L(t) || R(t)) return !0;
    for (let t of e.removedNodes)
        if (L(t) || R(t)) return !0;
    return !1
}

function wt(e) {
    class t extends e {
        #e = !1;
        #t = new Set;
        get destroyed() {
            return this.#e
        }
        destroy() {
            this.#e || (this.#e = !0, this.destroyCallback())
        }
        destroyCallback() {
            for (let e of this.#t) e.hostDestroyed?.()
        }
        addController(e) {
            super.addController(e), this.#t.add(e)
        }
        removeController(e) {
            super.removeController(e), this.#t.delete(e)
        }
        connectedCallback() {
            this.#e || super.connectedCallback()
        }
        disconnectedCallback() {
            super.disconnectedCallback(), !this.#e && !this.hasAttribute(`keep-alive`) && requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    this.isConnected || this.destroy()
                })
            })
        }
        performUpdate() {
            this.#e || super.performUpdate()
        }
    }
    return t
}
const Tt = new WeakMap,
    Et = new Map;
var Dt = class extends HTMLElement {
    static {
        this.properties = {}
    }
    static get observedAttributes() {
        return [...Ot(this).attrToProp.keys()]
    }
    #e = new Set;
    #t = new Map;
    #n;
    #r;
    constructor() {
        super(), this.isUpdatePending = !1, this.hasUpdated = !1, this.#r = new Promise(e => this.enableUpdating = e);
        let {
            props: e
        } = Ot(this.constructor);
        for (let t of e.keys()) Object.hasOwn(this, t) && ((this.#n ??= new Map).set(t, this[t]), delete this[t]);
        this.requestUpdate()
    }
    enableUpdating(e) {}
    addController(e) {
        this.#e.add(e), this.isConnected && e.hostConnected?.()
    }
    removeController(e) {
        this.#e.delete(e)
    }
    connectedCallback() {
        this.enableUpdating(!0);
        for (let e of this.#e) e.hostConnected?.()
    }
    disconnectedCallback() {
        for (let e of this.#e) e.hostDisconnected?.()
    }
    attributeChangedCallback(e, t, n) {
        if (t === n) return;
        let {
            props: r,
            attrToProp: i
        } = Ot(this.constructor), a = i.get(e);
        if (!a) return;
        let o = r.get(a);
        if (!o) return;
        let s = n;
        o.type === Boolean ? s = n !== null : o.type === Number && (s = n === null ? null : Number(n)), this[a] = s
    }
    requestUpdate(e, t) {
        e !== void 0 && this.#t.set(e, t), !this.isUpdatePending && (this.#r = this.#i())
    }
    async #i() {
        this.isUpdatePending = !0;
        try {
            await this.#r
        } catch (e) {
            Promise.reject(e)
        }
        let e = this.scheduleUpdate();
        return e != null && await e, !this.isUpdatePending
    }
    scheduleUpdate() {
        this.performUpdate()
    }
    performUpdate() {
        if (!this.isUpdatePending) return;
        if (!this.hasUpdated && this.#n) {
            for (let [e, t] of this.#n) this[e] = t;
            this.#n = void 0
        }
        let e = this.#t;
        this.willUpdate(e);
        for (let e of this.#e) e.hostUpdate?.();
        this.update(e), this.#t = new Map, this.isUpdatePending = !1;
        for (let e of this.#e) e.hostUpdated?.();
        this.hasUpdated || (this.hasUpdated = !0, this.firstUpdated(e)), this.updated(e)
    }
    willUpdate(e) {}
    update(e) {}
    firstUpdated(e) {}
    updated(e) {}
    get updateComplete() {
        return this.#r
    }
};

function Ot(e) {
    let t = Tt.get(e);
    if (t) return t;
    let n = new Map,
        r = new Map;
    for (let [t, i] of Object.entries(e.properties))
        if (n.set(t, i), r.set(i.attribute ?? t, t), !Object.getOwnPropertyDescriptor(e.prototype, t)?.get) {
            let n = Et.get(t);
            n || (n = Symbol(t), Et.set(t, n)), Object.defineProperty(e.prototype, t, {
                get() {
                    return this[n]
                },
                set(e) {
                    let r = this[n];
                    this[n] = e, Object.is(r, e) || this.requestUpdate(t, r)
                },
                configurable: !0,
                enumerable: !0
            })
        } let i = {
        props: n,
        attrToProp: r
    };
    return Tt.set(e, i), i
}
var z = class extends wt(Dt) {};
const kt = xt(I);
var At = class extends kt(z) {
    static {
        this.tagName = `media-container`
    }
};

function jt(e, t) {
    return n => {
        class r extends n {
            #e = t();
            #t = new F(this, {
                context: e,
                initialValue: this.store
            });
            get store() {
                return s(this.#e) && (this.#e = t()), this.#e
            }
            connectedCallback() {
                super.connectedCallback(), this.#t.setValue(this.store)
            }
            destroyCallback() {
                this.#e?.destroy(), this.#e = null, super.destroyCallback()
            }
        }
        return r
    }
}
var Mt = class {
        #e;
        #t;
        #n;
        #r;
        #i = _;
        constructor(e, t, n) {
            this.#e = e, this.#n = t, this.#t = n, e.addController(this)
        }
        get value() {
            return this.#t ? (this.#r ??= this.#t(this.#n.current), this.#r) : this.#n.current
        }
        track(e) {
            this.#n = e, this.#a()
        }
        hostConnected() {
            this.#a()
        }
        hostDisconnected() {
            this.#i(), this.#i = _, this.#r = void 0
        }
        #a() {
            if (this.#i(), !this.#t) {
                this.#i = this.#n.subscribe(() => this.#e.requestUpdate());
                return
            }
            let e = this.#t;
            this.#r = e(this.#n.current), this.#i = this.#n.subscribe(() => {
                let t = e(this.#n.current);
                h(this.#r, t) || (this.#r = t, this.#e.requestUpdate())
            })
        }
    },
    Nt = class {
        #e;
        #t;
        #n;
        constructor(e, t, n) {
            this.#e = n ?? _, se(t) ? (this.#n = t, this.#t = null) : (this.#n = null, this.#t = new P(e, {
                context: t,
                callback: e => this.#e(e),
                subscribe: !1
            })), e.addController(this)
        }
        get value() {
            return this.#t ? this.#t.value ?? null : this.#n
        }
        hostConnected() {
            this.#n && this.#e(this.#n)
        }
    },
    Pt = class {
        #e;
        #t;
        #n;
        #r = null;
        constructor(e, t, n) {
            this.#e = e, this.#t = n, this.#n = new Nt(e, t, e => this.#i(e)), e.addController(this)
        }
        get value() {
            let e = this.#n.value;
            if (s(e)) throw Error(`Store not available`);
            return c(this.#t) ? e : this.#r.value
        }
        hostConnected() {}
        #i(e) {
            c(this.#t) || (this.#r ? this.#r.track(e.$state) : this.#r = new Mt(this.#e, e.$state, this.#t))
        }
    },
    B = class {
        #e;
        #t;
        #n;
        #r = null;
        constructor(e, t, n) {
            this.#e = e, this.#t = n, this.#n = new P(e, {
                context: t,
                callback: e => this.#i(e),
                subscribe: !0
            }), e.addController(this)
        }
        get value() {
            let e = this.#n.value;
            if (e) return this.#t ? this.#r?.value : e
        }
        get displayName() {
            return this.#t?.displayName
        }
        hostConnected() {
            let e = this.#n.value;
            e && this.#i(e)
        }
        hostDisconnected() {
            this.#r = null
        }
        #i(e) {
            !this.#r && this.#t && (this.#r = new Pt(this.#e, e, this.#t))
        }
    };

function Ft(e) {
    let n = t(...e.features);

    function r() {
        return oe()(n)
    }
    return {
        context: I,
        create: r,
        PlayerController: B,
        ProviderMixin: jt(I, r),
        ContainerMixin: xt(I)
    }
}

function V(e) {
    customElements.get(e.tagName) || customElements.define(e.tagName, e)
}
const {
    ProviderMixin: It
} = Ft({
    features: Ve
});
V(class extends It(z) {
    static {
        this.tagName = `video-player`
    }
}), V(At);
const Lt = {
    "captions-off": `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="none" aria-hidden="true" viewBox="0 0 18 18"><rect width="16" height="12" x="1" y="3" stroke="currentColor" stroke-width="2" rx="3"/><rect width="3" height="2" x="3" y="8" fill="currentColor" rx="1"/><rect width="2" height="2" x="13" y="8" fill="currentColor" rx="1"/><rect width="4" height="2" x="11" y="11" fill="currentColor" rx="1"/><rect width="5" height="2" x="7" y="8" fill="currentColor" rx="1"/><rect width="7" height="2" x="3" y="11" fill="currentColor" rx="1"/></svg>`,
    "captions-on": `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="none" aria-hidden="true" viewBox="0 0 18 18"><path fill="currentColor" d="M15 2a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3H3a3 3 0 0 1-3-3V5a3 3 0 0 1 3-3zM4 11a1 1 0 1 0 0 2h5a1 1 0 1 0 0-2zm8 0a1 1 0 1 0 0 2h2a1 1 0 1 0 0-2zM4 8a1 1 0 0 0 0 2h1a1 1 0 0 0 0-2zm4 0a1 1 0 0 0 0 2h3a1 1 0 1 0 0-2zm6 0a1 1 0 1 0 0 2 1 1 0 0 0 0-2"/></svg>`,
    "fullscreen-enter": `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="none" aria-hidden="true" viewBox="0 0 18 18"><path fill="currentColor" d="M9.57 3.617A1 1 0 0 0 8.646 3H4c-.552 0-1 .449-1 1v4.646a.996.996 0 0 0 1.001 1 1 1 0 0 0 .706-.293l4.647-4.647a1 1 0 0 0 .216-1.089m4.812 4.812a1 1 0 0 0-1.089.217l-4.647 4.647a.998.998 0 0 0 .708 1.706H14c.552 0 1-.449 1-1V9.353a1 1 0 0 0-.618-.924"/></svg>`,
    "fullscreen-exit": `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="none" aria-hidden="true" viewBox="0 0 18 18"><path fill="currentColor" d="M7.883 1.93a.99.99 0 0 0-1.09.217L2.146 6.793A.998.998 0 0 0 2.853 8.5H7.5c.551 0 1-.449 1-1V2.854a1 1 0 0 0-.617-.924m7.263 7.57H10.5c-.551 0-1 .449-1 1v4.646a.996.996 0 0 0 1.001 1.001 1 1 0 0 0 .706-.293l4.646-4.646a.998.998 0 0 0-.707-1.707z"/></svg>`,
    pause: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="none" aria-hidden="true" viewBox="0 0 18 18"><rect width="5" height="14" x="2" y="2" fill="currentColor" rx="1.75"/><rect width="5" height="14" x="11" y="2" fill="currentColor" rx="1.75"/></svg>`,
    pip: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="none" aria-hidden="true" viewBox="0 0 18 18"><path fill="currentColor" d="M13 2a4 4 0 0 1 4 4v2.035A3.5 3.5 0 0 0 16.5 8H15V6.273C15 5.018 13.96 4 12.679 4H4.32C3.04 4 2 5.018 2 6.273v5.454C2 12.982 3.04 14 4.321 14H6v1.5q0 .255.035.5H4a4 4 0 0 1-4-4V6a4 4 0 0 1 4-4z"/><rect width="10" height="7" x="8" y="10" fill="currentColor" rx="2"/></svg>`,
    play: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="none" aria-hidden="true" viewBox="0 0 18 18"><path fill="currentColor" d="m14.051 10.723-7.985 4.964a1.98 1.98 0 0 1-2.758-.638A2.06 2.06 0 0 1 3 13.964V4.036C3 2.91 3.895 2 5 2c.377 0 .747.109 1.066.313l7.985 4.964a2.057 2.057 0 0 1 .627 2.808c-.16.257-.373.475-.627.637"/></svg>`,
    restart: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="none" aria-hidden="true" viewBox="0 0 18 18"><path fill="currentColor" d="M9 17a8 8 0 0 1-8-8h2a6 6 0 1 0 1.287-3.713l1.286 1.286A.25.25 0 0 1 5.396 7H1.25A.25.25 0 0 1 1 6.75V2.604a.25.25 0 0 1 .427-.177l1.438 1.438A8 8 0 1 1 9 17"/><path fill="currentColor" d="m11.61 9.639-3.331 2.07a.826.826 0 0 1-1.15-.266.86.86 0 0 1-.129-.452V6.849C7 6.38 7.374 6 7.834 6c.158 0 .312.045.445.13l3.331 2.071a.858.858 0 0 1 0 1.438"/></svg>`,
    seek: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="none" aria-hidden="true" viewBox="0 0 18 18"><path fill="currentColor" d="M1 9c0 2.21.895 4.21 2.343 5.657l1.414-1.414a6 6 0 1 1 8.956-7.956l-1.286 1.286a.25.25 0 0 0 .177.427h4.146a.25.25 0 0 0 .25-.25V2.604a.25.25 0 0 0-.427-.177l-1.438 1.438A8 8 0 0 0 1 9"/></svg>`,
    spinner: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="currentColor" aria-hidden="true" viewBox="0 0 18 18"><rect width="2" height="5" x="8" y=".5" opacity=".5" rx="1"><animate attributeName="opacity" begin="0s" calcMode="linear" dur="1s" repeatCount="indefinite" values="1;0"/></rect><rect width="2" height="5" x="12.243" y="2.257" opacity=".45" rx="1" transform="rotate(45 13.243 4.757)"><animate attributeName="opacity" begin="0.125s" calcMode="linear" dur="1s" repeatCount="indefinite" values="1;0"/></rect><rect width="5" height="2" x="12.5" y="8" opacity=".4" rx="1"><animate attributeName="opacity" begin="0.25s" calcMode="linear" dur="1s" repeatCount="indefinite" values="1;0"/></rect><rect width="5" height="2" x="10.743" y="12.243" opacity=".35" rx="1" transform="rotate(45 13.243 13.243)"><animate attributeName="opacity" begin="0.375s" calcMode="linear" dur="1s" repeatCount="indefinite" values="1;0"/></rect><rect width="2" height="5" x="8" y="12.5" opacity=".3" rx="1"><animate attributeName="opacity" begin="0.5s" calcMode="linear" dur="1s" repeatCount="indefinite" values="1;0"/></rect><rect width="2" height="5" x="3.757" y="10.743" opacity=".25" rx="1" transform="rotate(45 4.757 13.243)"><animate attributeName="opacity" begin="0.625s" calcMode="linear" dur="1s" repeatCount="indefinite" values="1;0"/></rect><rect width="5" height="2" x=".5" y="8" opacity=".15" rx="1"><animate attributeName="opacity" begin="0.75s" calcMode="linear" dur="1s" repeatCount="indefinite" values="1;0"/></rect><rect width="5" height="2" x="2.257" y="3.757" opacity=".1" rx="1" transform="rotate(45 4.757 4.757)"><animate attributeName="opacity" begin="0.875s" calcMode="linear" dur="1s" repeatCount="indefinite" values="1;0"/></rect></svg>`,
    "volume-high": `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="none" aria-hidden="true" viewBox="0 0 18 18"><path fill="currentColor" d="M15.6 3.3c-.4-.4-1-.4-1.4 0s-.4 1 0 1.4C15.4 5.9 16 7.4 16 9s-.6 3.1-1.8 4.3c-.4.4-.4 1 0 1.4.2.2.5.3.7.3.3 0 .5-.1.7-.3C17.1 13.2 18 11.2 18 9s-.9-4.2-2.4-5.7"/><path fill="currentColor" d="M.714 6.008h3.072l4.071-3.857c.5-.376 1.143 0 1.143.601V15.28c0 .602-.643.903-1.143.602l-4.071-3.858H.714c-.428 0-.714-.3-.714-.752V6.76c0-.451.286-.752.714-.752m10.568.59a.91.91 0 0 1 0-1.316.91.91 0 0 1 1.316 0c1.203 1.203 1.47 2.216 1.522 3.208q.012.255.011.51c0 1.16-.358 2.733-1.533 3.803a.7.7 0 0 1-.298.156c-.382.106-.873-.011-1.018-.156a.91.91 0 0 1 0-1.316c.57-.57.995-1.551.995-2.487 0-.944-.26-1.667-.995-2.402"/></svg>`,
    "volume-low": `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="none" aria-hidden="true" viewBox="0 0 18 18"><path fill="currentColor" d="M.714 6.008h3.072l4.071-3.857c.5-.376 1.143 0 1.143.601V15.28c0 .602-.643.903-1.143.602l-4.071-3.858H.714c-.428 0-.714-.3-.714-.752V6.76c0-.451.286-.752.714-.752m10.568.59a.91.91 0 0 1 0-1.316.91.91 0 0 1 1.316 0c1.203 1.203 1.47 2.216 1.522 3.208q.012.255.011.51c0 1.16-.358 2.733-1.533 3.803a.7.7 0 0 1-.298.156c-.382.106-.873-.011-1.018-.156a.91.91 0 0 1 0-1.316c.57-.57.995-1.551.995-2.487 0-.944-.26-1.667-.995-2.402"/></svg>`,
    "volume-off": `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" fill="none" aria-hidden="true" viewBox="0 0 18 18"><path fill="currentColor" d="M.714 6.008h3.072l4.071-3.857c.5-.376 1.143 0 1.143.601V15.28c0 .602-.643.903-1.143.602l-4.071-3.858H.714c-.428 0-.714-.3-.714-.752V6.76c0-.451.286-.752.714-.752M14.5 7.586l-1.768-1.768a1 1 0 1 0-1.414 1.414L13.085 9l-1.767 1.768a1 1 0 0 0 1.414 1.414l1.768-1.768 1.768 1.768a1 1 0 0 0 1.414-1.414L15.914 9l1.768-1.768a1 1 0 0 0-1.414-1.414z"/></svg>`
};

function H(e, t) {
    let n = Lt[e];
    if (!n) return ``;
    if (!t) return n;
    let r = Object.entries(t).map(([e, t]) => ` ${e}="${t}"`).join(``);
    return n.replace(`<svg`, `<svg${r}`)
}
var Rt = `video-player{display:contents}video-player video{object-fit:var(--media-object-fit,contain);object-position:var(--media-object-position,center);width:100%;height:100%;display:block}video-player video::-webkit-media-text-track-container{transition:transform var(--media-caption-track-duration,0) ease-out;transition-delay:var(--media-caption-track-delay,0);transform:translateY(var(--media-caption-track-y,0)) scale(.98);z-index:1;font-family:inherit}`;
const zt = `__media-styles`;

function Bt() {
    if (document.getElementById(zt)) return;
    let e = document.createElement(`style`);
    e.id = zt, e.textContent = Rt, document.head.appendChild(e)
}

function Vt(e) {
    class t extends e {
        static {
            this.shadowRootOptions = {
                mode: `open`
            }
        }
        constructor(...e) {
            if (super(...e), Bt(), !this.shadowRoot) {
                let e = this.constructor;
                this.attachShadow(e.shadowRootOptions), e.styles && (this.shadowRoot.adoptedStyleSheets = [e.styles]), e.getTemplateHTML && (this.shadowRoot.innerHTML = e.getTemplateHTML())
            }
        }
    }
    return t
}

function Ht(e) {
    let t = new CSSStyleSheet;
    return t.replaceSync(e), t
}
var Ut = `.media-button--play .media-icon--restart,.media-button--play .media-icon--play,.media-button--play .media-icon--pause,.media-button--mute .media-icon--volume-off,.media-button--mute .media-icon--volume-low,.media-button--mute .media-icon--volume-high,.media-button--fullscreen .media-icon--fullscreen-enter,.media-button--fullscreen .media-icon--fullscreen-exit,.media-button--captions .media-icon--captions-off,.media-button--captions .media-icon--captions-on{opacity:0;display:none}.media-button--play[data-ended] .media-icon--restart,.media-button--play:not([data-ended])[data-paused] .media-icon--play,.media-button--play:not([data-paused]):not([data-ended]) .media-icon--pause,.media-button--mute[data-muted] .media-icon--volume-off,.media-button--mute:not([data-muted])[data-volume-level=low] .media-icon--volume-low,.media-button--mute:not([data-muted]):not([data-volume-level=low]) .media-icon--volume-high,.media-button--fullscreen:not([data-fullscreen]) .media-icon--fullscreen-enter,.media-button--fullscreen[data-fullscreen] .media-icon--fullscreen-exit,.media-button--captions:not([data-active]) .media-icon--captions-off,.media-button--captions[data-active] .media-icon--captions-on{opacity:1;display:block}.media-tooltip-label{display:none}.media-button--play[data-ended]+.media-tooltip .media-tooltip-label--replay,.media-button--play:not([data-ended])[data-paused]+.media-tooltip .media-tooltip-label--play,.media-button--play:not([data-paused]):not([data-ended])+.media-tooltip .media-tooltip-label--pause,.media-button--fullscreen:not([data-fullscreen])+.media-tooltip .media-tooltip-label--enter-fullscreen,.media-button--fullscreen[data-fullscreen]+.media-tooltip .media-tooltip-label--exit-fullscreen,.media-button--captions:not([data-active])+.media-tooltip .media-tooltip-label--enable-captions,.media-button--captions[data-active]+.media-tooltip .media-tooltip-label--disable-captions,.media-button--pip:not([data-pip])+.media-tooltip .media-tooltip-label--enter-pip,.media-button--pip[data-pip]+.media-tooltip .media-tooltip-label--exit-pip{display:block}.media-default-skin *,.media-default-skin :before,.media-default-skin :after{box-sizing:border-box}.media-default-skin img,.media-default-skin video,.media-default-skin svg{max-width:100%;display:block}.media-default-skin button{font:inherit}@media (prefers-reduced-motion:no-preference){.media-default-skin{interpolate-size:allow-keywords}}.media-default-skin{isolation:isolate;border-radius:var(--media-border-radius,2rem);letter-spacing:normal;-webkit-font-smoothing:auto;-moz-osx-font-smoothing:auto;width:100%;height:100%;font-family:Inter Variable,Inter,ui-sans-serif,system-ui,sans-serif;font-size:.8125rem;line-height:1.5;display:block;position:relative;container:media-root/inline-size}.media-default-skin .media-surface{background-color:var(--media-surface-background-color);backdrop-filter:var(--media-surface-backdrop-filter);box-shadow:0 0 0 1px var(--media-surface-outer-border-color), 0 1px 3px 0 var(--media-surface-shadow-color), 0 1px 2px -1px var(--media-surface-shadow-color);&:after{content:"";z-index:10;border-radius:inherit;box-shadow:inset 0 0 0 1px var(--media-surface-inner-border-color);pointer-events:none;position:absolute;inset:0}@media (prefers-reduced-transparency:reduce){background-color:oklch(from var(--media-surface-background-color) l c h / .7)}@media (prefers-contrast:more){background-color:oklch(from var(--media-surface-background-color) l c h / .9)}}.media-default-skin ::slotted(video),.media-default-skin video{object-fit:var(--media-object-fit,contain);object-position:var(--media-object-position,center);width:100%;height:100%;display:block}.media-default-skin ::slotted(video){border-radius:var(--media-video-border-radius)}.media-default-skin video{border-radius:inherit}.media-default-skin>img{object-fit:var(--media-object-fit,contain);object-position:var(--media-object-position,center);pointer-events:none;border-radius:inherit;width:100%;height:100%;transition:opacity .25s;position:absolute;inset:0;&:not([data-visible]){opacity:0}}.media-default-skin:fullscreen ::slotted(video),.media-default-skin:fullscreen video{object-fit:contain}.media-default-skin .media-overlay{border-radius:inherit;backdrop-filter:blur()saturate(1.5);opacity:0;pointer-events:none;background-image:linear-gradient(oklch(0% 0 0/0),oklch(0% 0 0/.3),oklch(0% 0 0/.5));position:absolute;inset:0;@media (pointer:fine){transition:opacity .3s ease-out .5s,backdrop-filter .3s ease-out .5s;@media (prefers-reduced-motion:reduce){transition-duration:.1s}}}.media-default-skin .media-controls[data-visible]~.media-overlay,.media-default-skin .media-error[data-open]~.media-overlay{opacity:1;@media (pointer:fine){transition-duration:.15s;transition-delay:0s}}.media-default-skin .media-error[data-open]~.media-overlay{backdrop-filter:blur(16px)saturate(1.5)}.media-default-skin .media-buffering-indicator{color:oklch(100% 0 0);pointer-events:none;justify-content:center;align-items:center;display:none;position:absolute;inset:0;&[data-visible]{display:flex}& .media-surface{border-radius:100%;padding:.25rem}}.media-default-skin .media-error{z-index:20;justify-content:center;align-items:center;display:flex;position:absolute;inset:0}.media-default-skin .media-error__dialog{color:oklch(100% 0 0);max-width:18rem;transition-property:opacity,transform;transition-duration:.5s;transition-delay:.1s;transition-timing-function:linear(0, .034 1.5%, .763 9.7%, 1.066 13.9%, 1.198 19.9%, 1.184 21.8%, .963 37.5%, .997 50.9%, 1);border-radius:1.75rem;flex-direction:column;gap:.75rem;padding:.75rem;font-size:.875rem;display:flex;@media (prefers-reduced-motion:reduce){transition-duration:.1s;transition-delay:0s;transition-timing-function:ease-out}}.media-default-skin .media-error[data-starting-style] .media-error__dialog,.media-default-skin .media-error[data-ending-style] .media-error__dialog{opacity:0;transform:scale(.5)}.media-default-skin .media-error__content{flex-direction:column;gap:.5rem;padding:.5rem .5rem .375rem;display:flex}.media-default-skin .media-error__title{font-weight:600;line-height:1.25}.media-default-skin .media-error__description{opacity:.7}.media-default-skin .media-error__actions{gap:.5rem;display:flex;&>*{flex:1}}.media-default-skin .media-controls{--media-controls-current-shadow-color:oklch(from currentColor 0 0 0 / clamp(0, calc((l - .5) * .5), .25));--media-controls-current-shadow-color-subtle:oklch(from var(--media-controls-current-shadow-color) l c h / calc(alpha * .4));text-shadow:0 0 1px var(--media-controls-current-shadow-color);border-radius:3.40282e38px;align-items:center;gap:.075rem;padding:.175rem;display:flex;container:media-controls/inline-size;@container media-root (width>40rem){gap:.125rem;padding:.25rem}}.media-default-skin .media-time{flex:1;align-items:center;gap:.75rem;padding-inline:.5rem;display:flex;container:media-time/inline-size;& .media-time__value:first-child{display:none;@container media-time (width>18rem){display:block}}}.media-default-skin .media-time__value{font-variant-numeric:tabular-nums}.media-default-skin .media-button{outline-offset:-2px;color:oklch(0% 0 0);text-align:center;cursor:pointer;user-select:none;touch-action:manipulation;background:oklch(100% 0 0);border:none;border-radius:3.40282e38px;outline:2px solid #0000;flex-shrink:0;justify-content:center;align-items:center;padding:.5rem 1rem;font-weight:500;transition-property:background-color,color,outline-offset,transform;transition-duration:.15s;transition-timing-function:ease-out;display:flex;&:focus-visible{outline-offset:2px;outline-color:oklch(62.3% .214 259.815)}&[disabled]{opacity:.5;filter:grayscale();cursor:not-allowed}&[data-availability=unavailable]{display:none}}.media-default-skin .media-button--icon{aspect-ratio:1;width:2.125rem;color:inherit;text-shadow:inherit;background:0 0;padding:0;display:grid;&:hover,&:focus-visible,&[aria-expanded=true]{background-color:oklch(from currentColor l c h / .1);text-decoration:none}&:active{transform:scale(.9)}& .media-icon{filter:drop-shadow(0 1px 0 var(--media-controls-current-shadow-color,oklch(0% 0 0/.25)))}}.media-default-skin .media-button--seek{& .media-icon__label{font-variant-numeric:tabular-nums;font-size:.75em;font-weight:480;position:absolute;bottom:-3px;right:-1px}&:has(.media-icon--flipped) .media-icon__label{right:unset;left:-1px}@container media-controls (width<28rem){display:none}}.media-default-skin .media-button--playback-rate{padding:0;&:after{content:attr(data-rate) "×";font-variant-numeric:tabular-nums;width:4ch}}.media-default-skin .media-icon__container{position:relative}.media-default-skin .media-icon{transition-behavior:allow-discrete;flex-shrink:0;grid-area:1/1;width:18px;height:18px;transition-property:display,opacity;transition-duration:.15s;transition-timing-function:ease-out;display:block}.media-default-skin .media-icon--flipped{scale:-1 1}.media-default-skin .media-preview{background-color:oklch(0% 0 0/.9);border-radius:.75rem;& .media-preview__thumbnail{border-radius:inherit;display:block;position:relative;overflow:clip;&:after{content:"";border-radius:inherit;background-image:linear-gradient(oklch(0% 0 0/0),oklch(0% 0 0/.3),oklch(0% 0 0/.8));position:absolute;inset:0}}& .media-preview__timestamp{bottom:.5rem;text-align:center;font-variant-numeric:tabular-nums;position:absolute;inset-inline:0}& .media-overlay{opacity:1}& .media-preview__spinner{opacity:0;position:absolute;top:50%;left:50%;transform:translate(-50%,-50%)}& .media-preview__thumbnail,& .media-preview__spinner{transition:opacity .15s ease-out}&:has(.media-preview__thumbnail[data-loading]){& .media-preview__thumbnail{opacity:0}& .media-preview__spinner{opacity:1}}}.media-default-skin .media-slider{cursor:pointer;border-radius:3.40282e38px;outline:none;flex:1;justify-content:center;align-items:center;display:flex;position:relative;&[data-orientation=horizontal]{width:100%;min-width:5rem;height:1.25rem}&[data-orientation=vertical]{width:1.25rem;height:5rem}}.media-default-skin .media-slider__track{isolation:isolate;border-radius:inherit;user-select:none;position:relative;overflow:hidden;&[data-orientation=horizontal]{width:100%;height:.25rem}&[data-orientation=vertical]{width:.25rem;height:100%}}.media-default-skin .media-slider__thumb{z-index:10;width:.625rem;height:.625rem;box-shadow:0 0 0 1px var(--media-controls-current-shadow-color-subtle,oklch(0% 0 0/.1)), 0 1px 3px 0 oklch(0% 0 0/.15), 0 1px 2px -1px oklch(0% 0 0/.15);opacity:0;user-select:none;outline-offset:-4px;background-color:currentColor;border-radius:3.40282e38px;outline:4px solid #0000;transition-property:opacity,height,width,outline-offset;transition-duration:.15s;transition-timing-function:ease-out;position:absolute;transform:translate(-50%,-50%);&[data-orientation=horizontal]{top:50%;left:var(--media-slider-fill)}&[data-orientation=vertical]{left:50%;top:calc(100% - var(--media-slider-fill))}&:hover,&:focus{outline-color:oklch(from currentColor l c h / .25);outline-offset:0}}.media-default-skin .media-slider:active .media-slider__thumb,.media-default-skin .media-slider__thumb--persistent{width:.75rem;height:.75rem}.media-default-skin .media-slider:hover .media-slider__thumb,.media-default-skin .media-slider__thumb:focus-visible,.media-default-skin .media-slider__thumb--persistent{opacity:1}.media-default-skin .media-slider__buffer,.media-default-skin .media-slider__fill{border-radius:inherit;pointer-events:none;position:absolute}.media-default-skin .media-slider__buffer[data-orientation=horizontal],.media-default-skin .media-slider__fill[data-orientation=horizontal]{inset-block:0;left:0}.media-default-skin .media-slider__buffer[data-orientation=vertical],.media-default-skin .media-slider__fill[data-orientation=vertical]{inset-inline:0;bottom:0}.media-default-skin .media-slider__buffer{background-color:oklch(from currentColor l c h / .2);transition-duration:.25s;transition-timing-function:ease-out;&[data-orientation=horizontal]{width:var(--media-slider-buffer);transition-property:width}&[data-orientation=vertical]{height:var(--media-slider-buffer);transition-property:height}}.media-default-skin .media-slider__fill{background-color:currentColor;&[data-orientation=horizontal]{width:var(--media-slider-fill)}&[data-orientation=vertical]{height:var(--media-slider-fill)}}.media-default-skin .media-popover,.media-default-skin .media-tooltip{color:inherit;border:0;margin:0;transition-property:transform,scale,opacity,filter;transition-duration:.15s;overflow:visible;&[data-starting-style],&[data-ending-style]{opacity:0;filter:blur(8px);transform:scale(.5)}&[data-instant]{transition-duration:0s}&[data-side=top]{transform-origin:bottom}&[data-side=bottom]{transform-origin:top}&[data-side=left]{transform-origin:100%}&[data-side=right]{transform-origin:0}&:before{content:"";pointer-events:inherit;position:absolute}&[data-side=top]:before,&[data-side=bottom]:before{width:100%;inset-inline:0}&[data-side=top]:before{top:100%}&[data-side=bottom]:before{bottom:100%}&[data-side=left]:before,&[data-side=right]:before{height:100%;inset-block:0}&[data-side=left]:before{left:100%}&[data-side=right]:before{right:100%}}.media-default-skin .media-popover{--media-popover-side-offset:.5rem;&[data-side=top]:before,&[data-side=bottom]:before{height:var(--media-popover-side-offset)}&[data-side=left]:before,&[data-side=right]:before{width:var(--media-popover-side-offset)}}.media-default-skin .media-popover--volume{border-radius:3.40282e38px;padding:.625rem .25rem}.media-default-skin .media-tooltip{white-space:nowrap;--media-tooltip-side-offset:.75rem;border-radius:3.40282e38px;padding:.25rem .625rem;font-size:.75rem;&[data-side=top]:before,&[data-side=bottom]:before{height:var(--media-tooltip-side-offset)}&[data-side=left]:before,&[data-side=right]:before{width:var(--media-tooltip-side-offset)}}.media-default-skin{--media-caption-track-duration:.15s;--media-caption-track-delay:.6s;--media-caption-track-y:-.5rem;&:has(.media-controls[data-visible]){--media-caption-track-delay:25ms;--media-caption-track-y:-3.5rem}@media (prefers-reduced-motion:reduce){--media-caption-track-duration:50ms}}.media-default-skin video::-webkit-media-text-track-container{transition:transform var(--media-caption-track-duration) ease-out;transition-delay:var(--media-caption-track-delay);transform:translateY(var(--media-caption-track-y)) scale(.98);z-index:1;font-family:inherit}@media (prefers-reduced-motion:reduce){.media-default-skin video::-webkit-media-text-track-container{transition-duration:50ms}}.media-default-skin--video{--media-border-color:oklch(0% 0 0/.1);--media-surface-background-color:oklch(100% 0 0/.1);--media-surface-inner-border-color:oklch(100% 0 0/.05);--media-surface-outer-border-color:oklch(0% 0 0/.1);--media-surface-shadow-color:oklch(0% 0 0/.15);--media-surface-backdrop-filter:blur(16px) saturate(1.5);--media-video-border-radius:var(--media-border-radius,2rem);background:oklch(0% 0 0);@media (prefers-color-scheme:dark){--media-border-color:oklch(100% 0 0/.1)}&:after{content:"";z-index:10;border-radius:inherit;box-shadow:inset 0 0 0 1px var(--media-border-color);pointer-events:none;position:absolute;inset:0}&:fullscreen{--media-border-radius:0}}.media-default-skin--video .media-controls{bottom:.75rem;z-index:10;color:oklch(100% 0 0);will-change:scale, transform, filter, opacity;transform-origin:bottom;transition-timing-function:ease-out;position:absolute;inset-inline:.75rem;@media (pointer:fine){transition-property:scale,transform,filter,opacity;transition-duration:.1s;transition-delay:0s}&:not([data-visible]){opacity:0;pointer-events:none;filter:blur(8px);scale:.9;@media (pointer:fine){transition-duration:.3s;transition-delay:.5s;@media (prefers-reduced-motion:reduce){transition-duration:.1s}}@media (prefers-reduced-motion:reduce){filter:blur();scale:1}}}.media-default-skin--video:fullscreen:has(.media-controls:not([data-visible])){cursor:none}.media-default-skin--video .media-slider__track{background-color:oklch(100% 0 0/.2);box-shadow:0 0 0 1px oklch(0% 0 0/.05)}.media-default-skin .media-slider__preview{left:var(--media-slider-pointer);opacity:0;filter:blur(8px);transform-origin:bottom;transition-property:scale,opacity,filter;transition-duration:.15s;position:absolute;bottom:calc(100% + 1.2rem);translate:-50%;scale:.8;& .media-preview__thumbnail{max-width:11rem}&:has(.media-preview__thumbnail[data-loading]){max-height:6rem}}.media-default-skin .media-slider[data-pointing] .media-slider__preview:has([role=img]:not([data-hidden])){opacity:1;filter:blur();scale:1}media-tooltip-group{display:contents}:host{display:grid}`;
V(At);

function Wt(e) {
    return {
        transitionStarting: e === `starting`,
        transitionEnding: e === `ending`
    }
}
var Gt = class e {
    static defaultProps = {
        delay: 500
    };
    state = b({
        visible: !1
    });
    #e = {
        ...e.defaultProps
    };
    #t = null;
    setProps(t) {
        this.#e = u(t, e.defaultProps)
    }
    update(e) {
        let t = e.waiting && !e.paused;
        t && !this.state.current.visible && !this.#t ? this.#t = setTimeout(() => {
            this.#t = null, this.state.patch({
                visible: !0
            })
        }, this.#e.delay) : t || (this.#t !== null && (clearTimeout(this.#t), this.#t = null), this.state.patch({
            visible: !1
        }))
    }
};
const Kt = {
    visible: `data-visible`
};
var qt = class e {
    static defaultProps = {
        label: ``,
        disabled: !1
    };
    #e = {
        ...e.defaultProps
    };
    #t = null;
    constructor(e) {
        e && this.setProps(e)
    }
    setProps(t) {
        this.#e = u(t, e.defaultProps)
    }
    getLabel(e) {
        let {
            label: t
        } = this.#e;
        if (o(t)) {
            let n = t(e);
            if (n) return n
        } else if (t) return t;
        return e.subtitlesShowing ? `Disable captions` : `Enable captions`
    }
    getAttrs(e) {
        return {
            "aria-label": this.getLabel(e),
            "aria-disabled": this.#e.disabled ? `true` : void 0
        }
    }
    setMedia(e) {
        this.#t = e
    }
    getState() {
        let e = this.#t;
        return {
            subtitlesShowing: e.subtitlesShowing,
            availability: e.textTrackList.some(e => e.kind === `captions` || e.kind === `subtitles`) ? `available` : `unavailable`
        }
    }
    toggle(e) {
        this.#e.disabled || e.toggleSubtitles()
    }
};
const Jt = {
    subtitlesShowing: `data-active`,
    availability: `data-availability`
};
var Yt = class {
    #e = null;
    setMedia(e) {
        this.#e = e
    }
    getState() {
        let e = this.#e;
        return {
            visible: e.controlsVisible,
            userActive: e.userActive
        }
    }
};
const Xt = {
    visible: `data-visible`,
    userActive: `data-user-active`
};
var Zt = class e {
    static defaultProps = {
        label: ``,
        disabled: !1
    };
    #e = {
        ...e.defaultProps
    };
    #t = null;
    constructor(e) {
        e && this.setProps(e)
    }
    setProps(t) {
        this.#e = u(t, e.defaultProps)
    }
    getLabel(e) {
        let {
            label: t
        } = this.#e;
        if (o(t)) {
            let n = t(e);
            if (n) return n
        } else if (t) return t;
        return e.fullscreen ? `Exit fullscreen` : `Enter fullscreen`
    }
    getAttrs(e) {
        return {
            "aria-label": this.getLabel(e),
            "aria-disabled": this.#e.disabled ? `true` : void 0
        }
    }
    setMedia(e) {
        this.#t = e
    }
    getState() {
        let e = this.#t;
        return {
            fullscreen: e.fullscreen,
            availability: e.fullscreenAvailability
        }
    }
    async toggle(e) {
        if (!this.#e.disabled && e.fullscreenAvailability === `available`) try {
            e.fullscreen ? await e.exitFullscreen() : await e.requestFullscreen()
        } catch {}
    }
};
const Qt = {
    fullscreen: `data-fullscreen`,
    availability: `data-availability`
};
var $t = class e {
    static defaultProps = {
        label: ``,
        disabled: !1
    };
    #e = {
        ...e.defaultProps
    };
    #t = null;
    constructor(e) {
        e && this.setProps(e)
    }
    setProps(t) {
        this.#e = u(t, e.defaultProps)
    }
    getLabel(e) {
        let {
            label: t
        } = this.#e;
        if (o(t)) {
            let n = t(e);
            if (n) return n
        } else if (t) return t;
        return e.muted ? `Unmute` : `Mute`
    }
    getAttrs(e) {
        return {
            "aria-label": this.getLabel(e),
            "aria-disabled": this.#e.disabled ? `true` : void 0
        }
    }
    setMedia(e) {
        this.#t = e
    }
    getState() {
        let e = this.#t;
        return {
            muted: e.muted || e.volume === 0,
            volumeLevel: en(e)
        }
    }
    toggle(e) {
        this.#e.disabled || e.toggleMuted()
    }
};

function en(e) {
    return e.muted || e.volume === 0 ? `off` : e.volume < .5 ? `low` : e.volume < .75 ? `medium` : `high`
}
const tn = {
    muted: `data-muted`,
    volumeLevel: `data-volume-level`
};
var nn = class e {
    static defaultProps = {
        label: ``,
        disabled: !1
    };
    #e = {
        ...e.defaultProps
    };
    #t = null;
    constructor(e) {
        e && this.setProps(e)
    }
    setProps(t) {
        this.#e = u(t, e.defaultProps)
    }
    getLabel(e) {
        let {
            label: t
        } = this.#e;
        if (o(t)) {
            let n = t(e);
            if (n) return n
        } else if (t) return t;
        return e.pip ? `Exit picture-in-picture` : `Enter picture-in-picture`
    }
    getAttrs(e) {
        return {
            "aria-label": this.getLabel(e),
            "aria-disabled": this.#e.disabled ? `true` : void 0
        }
    }
    setMedia(e) {
        this.#t = e
    }
    getState() {
        let e = this.#t;
        return {
            pip: e.pip,
            availability: e.pipAvailability
        }
    }
    async toggle(e) {
        if (!this.#e.disabled && e.pipAvailability === `available`) try {
            e.pip ? await e.exitPictureInPicture() : await e.requestPictureInPicture()
        } catch {}
    }
};
const rn = {
    pip: `data-pip`,
    availability: `data-availability`
};
var an = class e {
    static defaultProps = {
        label: ``,
        disabled: !1
    };
    #e = {
        ...e.defaultProps
    };
    #t = null;
    constructor(e) {
        e && this.setProps(e)
    }
    setProps(t) {
        this.#e = u(t, e.defaultProps)
    }
    getLabel(e) {
        let {
            label: t
        } = this.#e;
        if (o(t)) {
            let n = t(e);
            if (n) return n
        } else if (t) return t;
        return e.ended ? `Replay` : e.paused ? `Play` : `Pause`
    }
    getAttrs(e) {
        return {
            "aria-label": this.getLabel(e),
            "aria-disabled": this.#e.disabled ? `true` : void 0
        }
    }
    setMedia(e) {
        this.#t = e
    }
    getState() {
        let e = this.#t;
        return {
            paused: e.paused,
            ended: e.ended,
            started: e.started
        }
    }
    async toggle(e) {
        if (!this.#e.disabled) {
            if (e.paused || e.ended) return e.play();
            e.pause()
        }
    }
};
const on = {
    paused: `data-paused`,
    ended: `data-ended`,
    started: `data-started`
};
var sn = class e {
    static defaultProps = {
        label: ``,
        disabled: !1
    };
    #e = {
        ...e.defaultProps
    };
    #t = null;
    constructor(e) {
        e && this.setProps(e)
    }
    setProps(t) {
        this.#e = u(t, e.defaultProps)
    }
    getLabel(e) {
        let {
            label: t
        } = this.#e;
        if (o(t)) {
            let n = t(e);
            if (n) return n
        } else if (t) return t;
        return `Playback rate ${e.rate}`
    }
    getAttrs(e) {
        return {
            "aria-label": this.getLabel(e),
            "aria-disabled": this.#e.disabled ? `true` : void 0
        }
    }
    setMedia(e) {
        this.#t = e
    }
    getState() {
        return {
            rate: this.#t.playbackRate
        }
    }
    cycle(e) {
        if (this.#e.disabled) return;
        let {
            playbackRates: t,
            playbackRate: n
        } = e;
        if (t.length === 0) return;
        let r = t.indexOf(n),
            i = r === -1 ? t.find(e => e > n) ?? t[0] : t[(r + 1) % t.length];
        e.setPlaybackRate(i)
    }
};
const cn = {
    rate: `data-rate`
};
var U = class e {
    static defaultProps = {
        side: `top`,
        align: `center`,
        modal: !1,
        closeOnEscape: !0,
        closeOnOutsideClick: !0,
        open: !1,
        defaultOpen: !1,
        openOnHover: !1,
        delay: 300,
        closeDelay: 0
    };
    #e = {
        ...e.defaultProps
    };
    constructor(e) {
        e && this.setProps(e)
    }
    setProps(t) {
        this.#e = u(t, e.defaultProps)
    }
    #t = null;
    setInput(e) {
        this.#t = e
    }
    getState() {
        let e = this.#t;
        return {
            open: e.active,
            status: e.status,
            side: this.#e.side,
            align: this.#e.align,
            modal: this.#e.modal,
            ...Wt(e.status)
        }
    }
    getTriggerAttrs(e, t) {
        return {
            "aria-expanded": e.open ? `true` : `false`,
            "aria-haspopup": `dialog`,
            "aria-controls": t
        }
    }
    getPopupAttrs(e) {
        return {
            popover: `manual`,
            role: `dialog`,
            "aria-modal": e.modal === !0 ? `true` : void 0
        }
    }
};
const ln = {
    open: `data-open`,
    side: `data-side`,
    align: `data-align`,
    transitionStarting: `data-starting-style`,
    transitionEnding: `data-ending-style`
};
var un = class e {
    static defaultProps = {
        seconds: 30,
        label: ``,
        disabled: !1
    };
    #e = {
        ...e.defaultProps
    };
    #t = null;
    constructor(e) {
        e && this.setProps(e)
    }
    setProps(t) {
        this.#e = u(t, e.defaultProps)
    }
    getLabel(e) {
        let {
            label: t
        } = this.#e;
        if (o(t)) {
            let n = t(e);
            if (n) return n
        } else if (t) return t;
        let n = Math.abs(this.#e.seconds);
        return e.direction === `backward` ? `Seek backward ${n} seconds` : `Seek forward ${n} seconds`
    }
    getAttrs(e) {
        return {
            "aria-label": this.getLabel(e),
            "aria-disabled": this.#e.disabled ? `true` : void 0
        }
    }
    setMedia(e) {
        this.#t = e
    }
    getState() {
        return {
            seeking: this.#t.seeking,
            direction: this.#e.seconds < 0 ? `backward` : `forward`
        }
    }
    async seek(e) {
        this.#e.disabled || await e.seek(e.currentTime + this.#e.seconds)
    }
};
const dn = {
    seeking: `data-seeking`,
    direction: `data-direction`
};
var W = class e {
    static defaultProps = {
        label: ``,
        step: 1,
        largeStep: 10,
        orientation: `horizontal`,
        disabled: !1,
        thumbAlignment: `center`,
        value: 0,
        min: 0,
        max: 100
    };
    static defaultInput = {
        pointerPercent: 0,
        dragPercent: 0,
        dragging: !1,
        pointing: !1,
        focused: !1
    };
    #e = {
        ...e.defaultProps
    };
    #t = {
        ...e.defaultInput
    };
    get props() {
        return this.#e
    }
    get input() {
        return this.#t
    }
    constructor(e) {
        e && this.setProps(e)
    }
    setProps(t) {
        this.#e = u(t, e.defaultProps)
    }
    setInput(e) {
        this.#t = e
    }
    getSliderState(e) {
        let {
            orientation: t,
            disabled: n,
            thumbAlignment: r
        } = this.#e, {
            pointerPercent: i,
            dragging: a,
            pointing: o,
            focused: s
        } = this.#t;
        return {
            value: e,
            fillPercent: this.percentFromValue(e),
            pointerPercent: i,
            dragging: a,
            pointing: o,
            interactive: a || o || s,
            orientation: t,
            disabled: n,
            thumbAlignment: r
        }
    }
    getLabel(e) {
        let {
            label: t
        } = this.#e;
        if (o(t)) {
            let n = t(e);
            if (n) return n
        } else if (t) return t;
        return ``
    }
    getAttrs(e) {
        return {
            role: `slider`,
            tabIndex: e.disabled ? -1 : 0,
            autoComplete: `off`,
            "aria-label": this.getLabel(e),
            "aria-valuemin": this.#e.min,
            "aria-valuemax": this.#e.max,
            "aria-valuenow": e.value,
            "aria-orientation": e.orientation,
            "aria-disabled": e.disabled ? `true` : void 0
        }
    }
    valueFromPercent(e) {
        let {
            min: t,
            max: n,
            step: r
        } = this.#e;
        return ot(O(t + e / 100 * (n - t), t, n), r, t)
    }
    percentFromValue(e) {
        let {
            min: t,
            max: n
        } = this.#e;
        return n === t ? 0 : (e - t) / (n - t) * 100
    }
    getStepPercent() {
        let {
            step: e,
            min: t,
            max: n
        } = this.#e, r = n - t;
        return r > 0 ? e / r * 100 : 0
    }
    getLargeStepPercent() {
        let {
            largeStep: e,
            min: t,
            max: n
        } = this.#e, r = n - t;
        return r > 0 ? e / r * 100 : 0
    }
    adjustPercentForAlignment(e, t, n) {
        if (this.#e.thumbAlignment === `center` || n === 0) return e;
        let r = t / n * 100 / 2,
            i = r,
            a = 100 - r;
        return i + e / 100 * (a - i)
    }
};
const G = {
        dragging: `data-dragging`,
        pointing: `data-pointing`,
        interactive: `data-interactive`,
        orientation: `data-orientation`,
        disabled: `data-disabled`
    },
    fn = {
        loading: `data-loading`,
        error: `data-error`,
        hidden: `data-hidden`
    };

function pn(e, t) {
    let n = e.trim().split(`#`),
        r = n[0] ?? ``,
        i = n[1],
        o = t ? new URL(r, t).href : r;
    if (!i) return {
        url: o
    };
    let s = i.indexOf(`=`);
    if (s === -1) return {
        url: o
    };
    let c = i.slice(0, s),
        l = i.slice(s + 1).split(`,`).map(Number),
        u = {};
    for (let e = 0; e < c.length; e++) {
        let t = c[e],
            n = l[e];
        t && a(n) && !Number.isNaN(n) && (u[t] = n)
    }
    let d = {
        url: o
    };
    return a(u.w) && (d.width = u.w), a(u.h) && (d.height = u.h), a(u.x) && a(u.y) && (d.coords = {
        x: u.x,
        y: u.y
    }), d
}

function mn(e, t) {
    let n = [];
    for (let r of e) {
        let e = pn(r.text, t),
            i = {
                url: e.url,
                startTime: r.startTime,
                endTime: r.endTime
            };
        e.width && (i.width = e.width), e.height && (i.height = e.height), e.coords && (i.coords = e.coords), n.push(i)
    }
    return n
}
const hn = [{
    singular: `hour`,
    plural: `hours`
}, {
    singular: `minute`,
    plural: `minutes`
}, {
    singular: `second`,
    plural: `seconds`
}];

function gn(e) {
    return a(e) && Number.isFinite(e)
}

function _n(e, t) {
    return `${e} ${e === 1 ? hn[t]?.singular : hn[t]?.plural}`
}

function vn(e, t) {
    if (!gn(e)) return `0:00`;
    let n = e < 0,
        r = Math.abs(e),
        i = Math.floor(r / 3600),
        a = Math.floor(r / 60 % 60),
        o = Math.floor(r % 60),
        s = t ? Math.abs(t) : 0,
        c = Math.floor(s / 3600),
        l = Math.floor(s / 60 % 60),
        u = i > 0 || c > 0,
        d = u || l >= 10,
        f = u ? `${i}:` : ``,
        p = `${d && a < 10 ? `0` : ``}${a}:`,
        m = o < 10 ? `0${o}` : `${o}`;
    return `${n ? `-` : ``}${f}${p}${m}`
}

function yn(e) {
    if (!gn(e)) return ``;
    let t = e < 0,
        n = Math.abs(e),
        r = Math.floor(n / 3600),
        i = Math.floor(n / 60 % 60),
        a = Math.floor(n % 60);
    return n === 0 ? `${_n(0, 2)}${t ? ` remaining` : ``}` : `${[r, i, a].map((e, t) => e > 0 ? _n(e, t) : null).filter(Boolean).join(`, `)}${t ? ` remaining` : ``}`
}

function bn(e) {
    if (!gn(e)) return `PT0S`;
    let t = Math.abs(e),
        n = Math.floor(t / 3600),
        r = Math.floor(t / 60 % 60),
        i = Math.floor(t % 60),
        a = `PT`;
    return n > 0 && (a += `${n}H`), r > 0 && (a += `${r}M`), (i > 0 || a === `PT`) && (a += `${i}S`), a
}
const xn = {
    current: `Current time`,
    duration: `Duration`,
    remaining: `Remaining`
};
var K = class e {
    static defaultProps = {
        type: `current`,
        negativeSign: `-`,
        label: ``
    };
    #e = {
        ...e.defaultProps
    };
    #t = null;
    constructor(e) {
        e && this.setProps(e)
    }
    setProps(t) {
        this.#e = u(t, e.defaultProps)
    }
    setMedia(e) {
        this.#t = e
    }
    #n() {
        let e = this.#t,
            {
                type: t
            } = this.#e;
        switch (t) {
            case `current`:
                return e.currentTime;
            case `duration`:
                return e.duration;
            case `remaining`:
                return e.currentTime - e.duration;
            default:
                return 0
        }
    }
    #r() {
        let e = this.#t,
            t = this.#n();
        return vn(Math.abs(t), e.duration)
    }
    #i() {
        let {
            type: e
        } = this.#e, t = this.#n();
        return yn(e === `remaining` ? t < 0 ? t : -Math.abs(t) : t)
    }
    #a() {
        let e = this.#n();
        return bn(Math.abs(e))
    }
    getLabel(e) {
        let {
            label: t
        } = this.#e;
        if (o(t)) {
            let n = t(e);
            if (n) return n
        } else if (t) return t;
        return xn[this.#e.type]
    }
    getAttrs(e) {
        return {
            "aria-label": this.getLabel(e),
            "aria-valuetext": e.phrase
        }
    }
    getState() {
        let e = this.#n();
        return {
            type: this.#e.type,
            seconds: e,
            negative: this.#e.type === `remaining` && e < 0,
            text: this.#r(),
            phrase: this.#i(),
            datetime: this.#a()
        }
    }
};
const Sn = {
    type: `data-type`
};
var q = class e extends W {
    static defaultProps = {
        ...W.defaultProps,
        label: `Seek`,
        commitThrottle: 100
    };
    #e = {
        ...e.defaultProps
    };
    #t = null;
    constructor(e) {
        super(), e && this.setProps(e)
    }
    setProps(t) {
        this.#e = u(t, e.defaultProps), super.setProps({
            ...t,
            min: 0
        })
    }
    setMedia(e) {
        this.#t = e
    }
    getState() {
        let {
            duration: e,
            currentTime: t,
            seeking: n,
            buffered: r
        } = this.#t, {
            dragging: i,
            dragPercent: a
        } = this.input;
        super.setProps({
            ...this.#e,
            min: 0,
            max: e
        });
        let o = i ? O(a / 100 * e, 0, e) : t,
            s = super.getSliderState(o),
            c = r.length > 0 ? r[r.length - 1][1] : 0,
            l = e > 0 ? c / e * 100 : 0;
        return {
            ...s,
            currentTime: t,
            duration: e,
            seeking: n,
            bufferPercent: l
        }
    }
    getLabel(e) {
        return super.getLabel(e) || `Seek`
    }
    getAttrs(e) {
        let t = super.getAttrs(e),
            n = yn(e.value),
            r = yn(e.duration),
            i = r ? `${n} of ${r}` : n;
        return {
            ...t,
            "aria-valuetext": i
        }
    }
};
const Cn = {
    ...G,
    seeking: `data-seeking`
};
var J = class e {
    static defaultProps = {
        side: `top`,
        align: `center`,
        open: !1,
        defaultOpen: !1,
        delay: 600,
        closeDelay: 0,
        disableHoverablePopup: !0,
        disabled: !1
    };
    #e = {
        ...e.defaultProps
    };
    constructor(e) {
        e && this.setProps(e)
    }
    setProps(t) {
        this.#e = u(t, e.defaultProps)
    }
    #t = null;
    setInput(e) {
        this.#t = e
    }
    getState() {
        let e = this.#t;
        return {
            open: e.active,
            status: e.status,
            side: this.#e.side,
            align: this.#e.align,
            ...Wt(e.status)
        }
    }
    getTriggerAttrs(e, t) {
        return {
            "aria-describedby": e.open ? t : void 0
        }
    }
    getPopupAttrs(e) {
        return {
            popover: `manual`,
            role: `tooltip`
        }
    }
};
const wn = {
        sideOffset: `--media-tooltip-side-offset`,
        alignOffset: `--media-tooltip-align-offset`,
        anchorWidth: `--media-tooltip-anchor-width`,
        anchorHeight: `--media-tooltip-anchor-height`,
        availableWidth: `--media-tooltip-available-width`,
        availableHeight: `--media-tooltip-available-height`
    },
    Tn = {
        open: `data-open`,
        side: `data-side`,
        align: `data-align`,
        transitionStarting: `data-starting-style`,
        transitionEnding: `data-ending-style`
    };
var Y = class e {
        static defaultProps = {
            delay: 600,
            closeDelay: 0,
            timeout: 400
        };
        #e = {
            ...e.defaultProps
        };
        #t = 0;
        #n = !1;
        constructor(e) {
            e && this.setProps(e)
        }
        setProps(t) {
            this.#e = u(t, e.defaultProps)
        }
        get delay() {
            return this.#e.delay
        }
        get closeDelay() {
            return this.#e.closeDelay
        }
        shouldSkipDelay() {
            return this.#n ? !0 : Date.now() - this.#t < this.#e.timeout
        }
        notifyOpen() {
            this.#n = !0
        }
        notifyClose() {
            this.#n = !1, this.#t = Date.now()
        }
    },
    X = class e extends W {
        static defaultProps = {
            ...W.defaultProps,
            label: `Volume`
        };
        #e = null;
        constructor(e) {
            super(), e && this.setProps(e)
        }
        setProps(t) {
            super.setProps(u(t, e.defaultProps))
        }
        setMedia(e) {
            this.#e = e
        }
        getState() {
            let {
                volume: e,
                muted: t
            } = this.#e, n = t || e === 0, {
                dragging: r,
                dragPercent: i
            } = this.input, a = e * 100, o = r ? this.valueFromPercent(i) : a, s = super.getSliderState(o);
            return {
                ...s,
                fillPercent: n ? 0 : s.fillPercent,
                volume: e,
                muted: n
            }
        }
        getLabel(e) {
            return super.getLabel(e) || `Volume`
        }
        getAttrs(e) {
            let t = super.getAttrs(e),
                n = `${Math.round(e.value)} percent${e.muted ? `, muted` : ``}`;
            return {
                ...t,
                "aria-valuetext": n
            }
        }
    };
({
    ...G
}), V(class extends z {
    constructor(...e) {
        super(...e), this.delay = Gt.defaultProps.delay
    }
    static {
        this.tagName = `media-buffering-indicator`
    }
    static {
        this.properties = {
            delay: {
                type: Number
            }
        }
    }
    #e = new Gt;
    #t = new B(this, I, Ke);
    #n = null;
    connectedCallback() {
        super.connectedCallback(), this.#n = new AbortController, this.#e.state.subscribe(() => this.requestUpdate(), {
            signal: this.#n.signal
        })
    }
    disconnectedCallback() {
        super.disconnectedCallback(), this.#n?.abort(), this.#n = null
    }
    willUpdate(e) {
        super.willUpdate(e), this.#e.setProps(this)
    }
    update(e) {
        super.update(e);
        let t = this.#t.value;
        t && (this.#e.update(t), M(this, this.#e.state.current, Kt))
    }
});
var Z = class extends z {
        constructor(...e) {
            super(...e), this.disabled = !1, this.label = ``
        }
        static {
            this.properties = {
                label: {
                    type: String
                },
                disabled: {
                    type: Boolean
                }
            }
        }
        #e = null;
        connectedCallback() {
            super.connectedCallback(), this.#e = new AbortController;
            let e = Qe({
                onActivate: () => this.activate(this.mediaState.value),
                isDisabled: () => this.disabled || !this.mediaState.value
            });
            j(this, e, {
                signal: this.#e.signal
            })
        }
        disconnectedCallback() {
            super.disconnectedCallback(), this.#e?.abort(), this.#e = null
        }
        willUpdate(e) {
            super.willUpdate(e), this.core.setProps?.(this)
        }
        update(e) {
            super.update(e);
            let t = this.mediaState.value;
            if (!t) return;
            this.core.setMedia(t);
            let n = this.core.getState();
            j(this, this.core.getAttrs?.(n) ?? {}), M(this, n, this.stateAttrMap)
        }
    },
    En = class extends Z {
        constructor(...e) {
            super(...e), this.core = new qt, this.stateAttrMap = Jt, this.mediaState = new B(this, I, Je)
        }
        static {
            this.tagName = `media-captions-button`
        }
        activate(e) {
            this.core.toggle(e)
        }
    };
customElements.define(En.tagName, En);
const Dn = N(Symbol(`@videojs/controls`));
var On = class extends z {
        static {
            this.tagName = `media-controls`
        }
        #e = new Yt;
        #t = new B(this, I, Ue);
        #n = new F(this, {
            context: Dn
        });
        connectedCallback() {
            super.connectedCallback()
        }
        update(e) {
            super.update(e);
            let t = this.#t.value;
            if (!t) return;
            this.#e.setMedia(t);
            let n = this.#e.getState();
            M(this, n, Xt), this.#n.setValue({
                state: n,
                stateAttrMap: Xt
            })
        }
    },
    Q = class extends z {
        update(e) {
            super.update(e);
            let t = this.consumer.value;
            t && M(this, t.state, t.stateAttrMap)
        }
    },
    kn = class extends Q {
        constructor(...e) {
            super(...e), this.consumer = new P(this, {
                context: Dn,
                subscribe: !0
            })
        }
        static {
            this.tagName = `media-controls-group`
        }
        connectedCallback() {
            super.connectedCallback(), (this.hasAttribute(`aria-label`) || this.hasAttribute(`aria-labelledby`)) && this.setAttribute(`role`, `group`)
        }
    };
V(On), V(kn), V(class extends Z {
    constructor(...e) {
        super(...e), this.core = new Zt, this.stateAttrMap = Qt, this.mediaState = new B(this, I, We)
    }
    static {
        this.tagName = `media-fullscreen-button`
    }
    activate(e) {
        this.core.toggle(e)
    }
}), V(class extends Z {
    constructor(...e) {
        super(...e), this.core = new $t, this.stateAttrMap = tn, this.mediaState = new B(this, I, Xe)
    }
    static {
        this.tagName = `media-mute-button`
    }
    activate(e) {
        this.core.toggle(e)
    }
}), V(class extends Z {
    constructor(...e) {
        super(...e), this.core = new nn, this.stateAttrMap = rn, this.mediaState = new B(this, I, Ge)
    }
    static {
        this.tagName = `media-pip-button`
    }
    activate(e) {
        this.core.toggle(e)
    }
}), V(class extends Z {
    constructor(...e) {
        super(...e), this.core = new an, this.stateAttrMap = on, this.mediaState = new B(this, I, Ke)
    }
    static {
        this.tagName = `media-play-button`
    }
    activate(e) {
        this.core.toggle(e)
    }
}), V(class extends Z {
    constructor(...e) {
        super(...e), this.core = new sn, this.stateAttrMap = cn, this.mediaState = new B(this, I, qe)
    }
    static {
        this.tagName = `media-playback-rate-button`
    }
    activate(e) {
        this.core.cycle(e)
    }
}), V(class extends z {
    constructor(...e) {
        super(...e), this.open = U.defaultProps.open, this.defaultOpen = U.defaultProps.defaultOpen, this.side = U.defaultProps.side, this.align = U.defaultProps.align, this.modal = U.defaultProps.modal, this.closeOnEscape = U.defaultProps.closeOnEscape, this.closeOnOutsideClick = U.defaultProps.closeOnOutsideClick, this.openOnHover = U.defaultProps.openOnHover, this.delay = U.defaultProps.delay, this.closeDelay = U.defaultProps.closeDelay
    }
    static {
        this.tagName = `media-popover`
    }
    static {
        this.properties = {
            open: {
                type: Boolean
            },
            defaultOpen: {
                type: Boolean,
                attribute: `default-open`
            },
            side: {
                type: String
            },
            align: {
                type: String
            },
            modal: {
                type: Boolean
            },
            closeOnEscape: {
                type: Boolean,
                attribute: `close-on-escape`
            },
            closeOnOutsideClick: {
                type: Boolean,
                attribute: `close-on-outside-click`
            },
            openOnHover: {
                type: Boolean,
                attribute: `open-on-hover`
            },
            delay: {
                type: Number
            },
            closeDelay: {
                type: Number,
                attribute: `close-delay`
            }
        }
    }
    #e = new U;
    #t = null;
    #n = null;
    #r = null;
    #i = null;
    #a = null;
    connectedCallback() {
        super.connectedCallback(), !this.destroyed && (this.#r = new AbortController, this.#t = $e({
            transition: ht(),
            onOpenChange: (e, t) => {
                this.open = e, this.dispatchEvent(new CustomEvent(`open-change`, {
                    detail: {
                        open: e,
                        ...t
                    }
                }))
            },
            closeOnEscape: () => this.closeOnEscape,
            closeOnOutsideClick: () => this.closeOnOutsideClick,
            openOnHover: () => this.openOnHover,
            delay: () => this.delay,
            closeDelay: () => this.closeDelay
        }), this.#t.setPopupElement(this), j(this, this.#t.popupProps, {
            signal: this.#r.signal
        }), this.#n ? this.#n.track(this.#t.input) : this.#n = new Mt(this, this.#t.input))
    }
    firstUpdated(e) {
        super.firstUpdated(e), this.defaultOpen && !this.open && this.#t?.open()
    }
    disconnectedCallback() {
        super.disconnectedCallback(), this.#r?.abort(), this.#r = null
    }
    destroyCallback() {
        this.#c(), this.#t?.destroy(), super.destroyCallback()
    }
    willUpdate(e) {
        if (super.willUpdate(e), this.#e.setProps(this), this.#t && e.has(`open`)) {
            let {
                active: e
            } = this.#t.input.current;
            this.open !== e && (this.open ? this.#t.open() : this.#t.close())
        }
    }
    update(e) {
        if (super.update(e), !this.#t) return;
        let t = this.#o();
        this.#s(t);
        let n = this.#t.input.current;
        this.#e.setInput(n);
        let r = this.#e.getState();
        if (j(this, this.#e.getPopupAttrs(r)), M(this, r, ln), r.open ? ue(this) : w(this), this.#a && (j(this.#a, this.#e.getTriggerAttrs(r, this.id)), T(this.#a, tt(this.id))), !r.open) return;
        let i = {
            side: r.side,
            align: r.align
        };
        if (S()) T(this, D(this.id, i));
        else {
            let e = this.#a?.getBoundingClientRect(),
                t = this.getBoundingClientRect(),
                n = document.documentElement.getBoundingClientRect(),
                r = at(this);
            T(this, D(this.id, i, e, t, n, r))
        }
    }
    #o() {
        return this.id ? this.getRootNode().querySelector(`[commandfor="${this.id}"]`) : null
    }
    #s(e) {
        e !== this.#a && (this.#c(), this.#a = e, this.#t?.setTriggerElement(e), e && this.#t && (this.#i = new AbortController, j(e, this.#t.triggerProps, {
            signal: this.#i.signal
        })))
    }
    #c() {
        this.#a && (j(this.#a, {
            "aria-expanded": void 0,
            "aria-haspopup": void 0,
            "aria-controls": void 0
        }), this.#a.style.removeProperty(`anchor-name`)), this.#i?.abort(), this.#i = null, this.#a = null
    }
}), V(class extends Z {
    constructor(...e) {
        super(...e), this.seconds = un.defaultProps.seconds, this.core = new un, this.stateAttrMap = dn, this.mediaState = new B(this, I, Ye)
    }
    static {
        this.tagName = `media-seek-button`
    }
    static {
        this.properties = {
            ...Z.properties,
            seconds: {
                type: Number
            }
        }
    }
    activate(e) {
        this.core.seek(e)
    }
});
var An = class extends z {
        static {
            this.tagName = `media-time`
        }
        static {
            this.properties = {
                type: {
                    type: String
                },
                negativeSign: {
                    type: String,
                    attribute: `negative-sign`
                },
                label: {
                    type: String
                }
            }
        }
        #e = new K;
        #t = new B(this, I, Ye);
        #n = document.createElement(`span`);
        #r = document.createTextNode(``);
        constructor() {
            super(), this.type = K.defaultProps.type, this.negativeSign = K.defaultProps.negativeSign, this.label = K.defaultProps.label, this.#n.setAttribute(`aria-hidden`, `true`), this.#n.hidden = !0, this.appendChild(this.#n), this.appendChild(this.#r)
        }
        connectedCallback() {
            super.connectedCallback()
        }
        willUpdate(e) {
            super.willUpdate(e), this.#e.setProps(this)
        }
        update(e) {
            super.update(e);
            let t = this.#t.value;
            if (!t) return;
            this.#e.setMedia(t);
            let n = this.#e.getState();
            this.#n.hidden = !n.negative, this.#n.textContent = n.negative ? this.negativeSign : ``, this.#r.textContent = n.text, j(this, this.#e.getAttrs(n)), M(this, n, Sn)
        }
    },
    jn = class extends z {
        static {
            this.tagName = `media-time-group`
        }
    },
    Mn = class extends z {
        static {
            this.tagName = `media-time-separator`
        }
        connectedCallback() {
            super.connectedCallback(), this.setAttribute(`aria-hidden`, `true`), this.textContent?.trim() || (this.textContent = `/`)
        }
    };
V(An), V(jn), V(Mn);
const $ = N(Symbol(`@videojs/slider`));
var Nn = class extends Q {
        constructor(...e) {
            super(...e), this.consumer = new P(this, {
                context: $,
                subscribe: !0
            })
        }
        static {
            this.tagName = `media-slider-buffer`
        }
    },
    Pn = class extends Q {
        constructor(...e) {
            super(...e), this.consumer = new P(this, {
                context: $,
                subscribe: !0
            })
        }
        static {
            this.tagName = `media-slider-fill`
        }
    },
    Fn = class extends z {
        constructor(...e) {
            super(...e), this.overflow = `clamp`
        }
        static {
            this.tagName = `media-slider-preview`
        }
        static {
            this.properties = {
                overflow: {
                    type: String
                }
            }
        }
        #e = new P(this, {
            context: $,
            subscribe: !0
        });
        #t = null;
        #n = 0;
        connectedCallback() {
            super.connectedCallback(), this.#t = new ResizeObserver(([e]) => {
                this.#n = e.contentRect.width, this.#r()
            }), this.#t.observe(this)
        }
        disconnectedCallback() {
            super.disconnectedCallback(), this.#t?.disconnect(), this.#t = null
        }
        #r() {
            T(this, ut(this.#n, this.overflow))
        }
        update(e) {
            super.update(e);
            let t = this.#e.value;
            t && M(this, t.state, t.stateAttrMap), this.#r()
        }
    },
    In = class extends z {
        static {
            this.tagName = `media-slider-thumb`
        }
        #e = new P(this, {
            context: $,
            subscribe: !0
        });
        #t = null;
        #n = !1;
        connectedCallback() {
            super.connectedCallback(), this.#t = new AbortController, this.#n = !1
        }
        disconnectedCallback() {
            super.disconnectedCallback(), this.#t?.abort(), this.#t = null, this.#n = !1
        }
        update(e) {
            super.update(e);
            let t = this.#e.value;
            t && (!this.#n && this.#t && (j(this, t.thumbProps, {
                signal: this.#t.signal
            }), this.#n = !0), j(this, t.thumbAttrs), M(this, t.state, t.stateAttrMap))
        }
    },
    Ln = class extends z {
        static {
            this.tagName = `media-thumbnail`
        }
        static {
            this.properties = {
                time: {
                    type: Number
                },
                crossOrigin: {
                    type: String,
                    attribute: `crossorigin`
                },
                loading: {
                    type: String
                },
                fetchPriority: {
                    type: String,
                    attribute: `fetchpriority`
                }
            }
        }
        #e = new dt;
        #t = document.createElement(`img`);
        #n = new B(this, I, Je);
        #r = [];
        #i;
        #a;
        #o = null;
        constructor() {
            super(), this.time = 0;
            let e = this.attachShadow({
                    mode: `open`
                }),
                t = document.createElement(`style`);
            t.textContent = `:host {
  display: inline-block;
  overflow: hidden;
}
img {
  display: block;
}`, e.appendChild(t), this.#t.alt = ``, this.#t.setAttribute(`part`, `img`), this.#t.setAttribute(`aria-hidden`, `true`), this.#t.setAttribute(`decoding`, `async`), e.appendChild(this.#t)
        }
        get thumbnails() {
            return this.#i
        }
        set thumbnails(e) {
            this.#i = e, this.requestUpdate()
        }
        connectedCallback() {
            super.connectedCallback(), !this.destroyed && (this.#o = ft({
                getContainer: () => this,
                getImg: () => this.#t,
                onStateChange: () => this.requestUpdate()
            }))
        }
        disconnectedCallback() {
            super.disconnectedCallback()
        }
        destroyCallback() {
            this.#o?.destroy(), super.destroyCallback()
        }
        update(e) {
            if (super.update(e), this.#i) this.#r = this.#i;
            else {
                let e = this.#n.value;
                e !== this.#a && (this.#a = e, this.#r = e && e.thumbnailCues.length > 0 ? mn(e.thumbnailCues, e.thumbnailTrackSrc ?? void 0) : [])
            }
            let t = this.#e.findActiveThumbnail(this.#r, this.time);
            if (j(this.#t, {
                    crossorigin: this.crossOrigin || void 0,
                    loading: this.loading,
                    fetchpriority: this.fetchPriority
                }), this.#o?.updateSrc(t?.url), !t) {
                this.#t.removeAttribute(`src`), this.#c();
                let e = this.#e.getState(!1, !1, void 0);
                j(this, this.#e.getAttrs(e)), M(this, e, fn);
                return
            }
            this.#t.getAttribute(`src`) !== t.url && (this.#t.src = t.url);
            let n = this.#o,
                r = this.#e.getState(n?.loading ?? !1, n?.error ?? !1, t);
            if (j(this, this.#e.getAttrs(r)), M(this, r, fn), n?.naturalWidth && n.naturalHeight) {
                let e = n.readConstraints(),
                    r = this.#e.resize(t, n.naturalWidth, n.naturalHeight, e);
                r && this.#s(r)
            }
        }
        #s(e) {
            this.style.width = `${e.containerWidth}px`, this.style.height = `${e.containerHeight}px`;
            let t = this.#t.style;
            t.width = `${e.imageWidth}px`, t.height = `${e.imageHeight}px`, t.maxWidth = `none`, t.transform = e.offsetX || e.offsetY ? `translate(-${e.offsetX}px, -${e.offsetY}px)` : ``
        }
        #c() {
            this.style.width = ``, this.style.height = ``;
            let e = this.#t.style;
            e.width = ``, e.height = ``, e.maxWidth = ``, e.transform = ``
        }
    },
    Rn = class extends Ln {
        static {
            this.tagName = `media-slider-thumbnail`
        }
        #e = new P(this, {
            context: $,
            subscribe: !0
        });
        update(e) {
            let t = this.#e.value;
            t && (this.time = t.pointerValue), super.update(e)
        }
    },
    zn = class extends Q {
        constructor(...e) {
            super(...e), this.consumer = new P(this, {
                context: $,
                subscribe: !0
            })
        }
        static {
            this.tagName = `media-slider-track`
        }
    },
    Bn = class extends z {
        constructor(...e) {
            super(...e), this.type = `current`
        }
        static {
            this.tagName = `media-slider-value`
        }
        static {
            this.properties = {
                type: {
                    type: String
                }
            }
        }
        #e = new P(this, {
            context: $,
            subscribe: !0
        });
        connectedCallback() {
            super.connectedCallback(), this.setAttribute(`aria-live`, `off`)
        }
        update(e) {
            super.update(e);
            let t = this.#e.value;
            if (!t) return;
            let n = this.type === `pointer` ? t.pointerValue : t.state.value;
            this.textContent = t.formatValue ? t.formatValue(n, this.type) : String(Math.round(n)), M(this, t.state, t.stateAttrMap)
        }
    };
V(class extends z {
    constructor(...e) {
        super(...e), this.label = q.defaultProps.label, this.commitThrottle = q.defaultProps.commitThrottle, this.step = q.defaultProps.step, this.largeStep = q.defaultProps.largeStep, this.orientation = q.defaultProps.orientation, this.disabled = q.defaultProps.disabled, this.thumbAlignment = q.defaultProps.thumbAlignment
    }
    static {
        this.tagName = `media-time-slider`
    }
    static {
        this.properties = {
            label: {
                type: String
            },
            commitThrottle: {
                type: Number,
                attribute: `commit-throttle`
            },
            step: {
                type: Number
            },
            largeStep: {
                type: Number,
                attribute: `large-step`
            },
            orientation: {
                type: String
            },
            disabled: {
                type: Boolean
            },
            thumbAlignment: {
                type: String,
                attribute: `thumb-alignment`
            }
        }
    }
    #e = new q;
    #t = new F(this, {
        context: $
    });
    #n = new B(this, I, Ye);
    #r = new B(this, I, He);
    #i = null;
    #a = null;
    connectedCallback() {
        if (super.connectedCallback(), this.destroyed) return;
        this.#a = new AbortController;
        let e = this.#a.signal;
        this.#i = st({
            getElement: () => this,
            getThumbElement: () => this.querySelector(`media-slider-thumb`),
            getOrientation: () => this.orientation,
            isRTL: () => ce(this),
            isDisabled: () => this.disabled || !this.#n.value,
            getPercent: () => {
                let e = this.#n.value;
                return e ? this.#e.percentFromValue(e.currentTime) : 0
            },
            getStepPercent: () => this.#e.getStepPercent(),
            getLargeStepPercent: () => this.#e.getLargeStepPercent(),
            onValueCommit: e => {
                let t = this.#n.value;
                t && t.seek(this.#e.valueFromPercent(e))
            },
            commitThrottle: this.commitThrottle,
            onDragStart: () => {
                this.dispatchEvent(new CustomEvent(`drag-start`, {
                    bubbles: !0
                }))
            },
            onDragEnd: () => {
                this.dispatchEvent(new CustomEvent(`drag-end`, {
                    bubbles: !0
                }))
            },
            adjustPercent: (e, t, n) => this.#e.adjustPercentForAlignment(e, t, n),
            onResize: () => this.requestUpdate()
        }), j(this, this.#i.rootProps, {
            signal: e
        }), T(this, this.#i.rootStyle), this.#i.input.subscribe(() => this.requestUpdate(), {
            signal: e
        })
    }
    disconnectedCallback() {
        super.disconnectedCallback(), this.#a?.abort(), this.#a = null
    }
    destroyCallback() {
        this.#i?.destroy(), super.destroyCallback()
    }
    willUpdate(e) {
        super.willUpdate(e), this.#e.setProps(this)
    }
    update(e) {
        if (super.update(e), !this.#i) return;
        let t = this.#n.value,
            n = this.#r.value;
        if (!t) return;
        this.#e.setInput(this.#i.input.current);
        let r = {
            ...t,
            ...n ?? {
                buffered: [],
                seekable: []
            }
        };
        this.#e.setMedia(r);
        let i = this.#e.getState(),
            a = lt(this.#i.adjustForAlignment(i));
        T(this, a), M(this, i, Cn), this.#t.setValue({
            state: i,
            stateAttrMap: Cn,
            pointerValue: this.#e.valueFromPercent(i.pointerPercent),
            thumbAttrs: this.#e.getAttrs(i),
            thumbProps: this.#i.thumbProps,
            formatValue: e => vn(e, i.duration)
        })
    }
}), V(Nn), V(Pn), V(Fn), V(In), V(Rn), V(zn), V(Bn);
const Vn = N(Symbol(`@videojs/tooltip-group`));
V(class extends z {
    constructor(...e) {
        super(...e), this.open = J.defaultProps.open, this.defaultOpen = J.defaultProps.defaultOpen, this.side = J.defaultProps.side, this.align = J.defaultProps.align, this.delay = J.defaultProps.delay, this.closeDelay = J.defaultProps.closeDelay, this.disableHoverablePopup = J.defaultProps.disableHoverablePopup, this.disabled = J.defaultProps.disabled
    }
    static {
        this.tagName = `media-tooltip`
    }
    static {
        this.properties = {
            open: {
                type: Boolean
            },
            defaultOpen: {
                type: Boolean,
                attribute: `default-open`
            },
            side: {
                type: String
            },
            align: {
                type: String
            },
            delay: {
                type: Number
            },
            closeDelay: {
                type: Number,
                attribute: `close-delay`
            },
            disableHoverablePopup: {
                type: Boolean,
                attribute: `disable-hoverable-popup`
            },
            disabled: {
                type: Boolean
            }
        }
    }
    #e = new J;
    #t = new P(this, {
        context: Vn
    });
    #n = null;
    #r = null;
    #i = null;
    #a = null;
    #o = null;
    connectedCallback() {
        super.connectedCallback(), this.#i = new AbortController, this.#n = mt({
            transition: ht(),
            onOpenChange: (e, t) => {
                this.open = e, this.dispatchEvent(new CustomEvent(`open-change`, {
                    detail: {
                        open: e,
                        ...t
                    }
                }))
            },
            delay: () => this.delay,
            closeDelay: () => this.closeDelay,
            disableHoverablePopup: () => this.disableHoverablePopup,
            disabled: () => this.disabled,
            group: () => this.#t.value
        }), this.#n.setPopupElement(this), j(this, this.#n.popupProps, {
            signal: this.#i.signal
        }), this.#r ? this.#r.track(this.#n.input) : this.#r = new Mt(this, this.#n.input)
    }
    firstUpdated(e) {
        super.firstUpdated(e), this.defaultOpen && !this.open && this.#n?.open()
    }
    disconnectedCallback() {
        super.disconnectedCallback(), this.#l(), this.#n?.destroy(), this.#n = null, this.#i?.abort(), this.#i = null
    }
    willUpdate(e) {
        if (super.willUpdate(e), this.#e.setProps(this), this.#n && e.has(`open`)) {
            let {
                active: e
            } = this.#n.input.current;
            this.open !== e && (this.open ? this.#n.open() : this.#n.close())
        }
    }
    update(e) {
        if (super.update(e), !this.#n) return;
        let t = this.#s();
        this.#c(t);
        let n = this.#n.input.current;
        this.#e.setInput(n);
        let r = this.#e.getState();
        if (j(this, this.#e.getPopupAttrs(r)), M(this, r, Tn), r.open ? ue(this) : w(this), this.#o && (j(this.#o, this.#e.getTriggerAttrs(r, this.id)), T(this.#o, tt(this.id))), !r.open) return;
        let i = {
            side: r.side,
            align: r.align
        };
        if (S()) T(this, D(this.id, i, void 0, void 0, void 0, void 0, wn));
        else {
            let e = this.#o?.getBoundingClientRect(),
                t = this.getBoundingClientRect(),
                n = document.documentElement.getBoundingClientRect(),
                r = at(this, wn);
            T(this, D(this.id, i, e, t, n, r, wn))
        }
    }
    #s() {
        return this.id ? this.getRootNode().querySelector(`[commandfor="${this.id}"]`) : null
    }
    #c(e) {
        e !== this.#o && (this.#l(), this.#o = e, this.#n?.setTriggerElement(e), e && this.#n && (this.#a = new AbortController, j(e, this.#n.triggerProps, {
            signal: this.#a.signal
        })))
    }
    #l() {
        this.#o && (j(this.#o, {
            "aria-describedby": void 0
        }), this.#o.style.removeProperty(`anchor-name`)), this.#a?.abort(), this.#a = null, this.#o = null
    }
}), V(class extends z {
    constructor(...e) {
        super(...e), this.delay = Y.defaultProps.delay, this.closeDelay = Y.defaultProps.closeDelay, this.timeout = Y.defaultProps.timeout
    }
    static {
        this.tagName = `media-tooltip-group`
    }
    static {
        this.properties = {
            delay: {
                type: Number
            },
            closeDelay: {
                type: Number,
                attribute: `close-delay`
            },
            timeout: {
                type: Number
            }
        }
    }
    #e = new Y;
    #t = new F(this, {
        context: Vn,
        initialValue: this.#e
    });
    update(e) {
        super.update(e), this.#e.setProps(this), this.#t.setValue(this.#e)
    }
}), V(class extends z {
    constructor(...e) {
        super(...e), this.label = X.defaultProps.label, this.step = X.defaultProps.step, this.largeStep = X.defaultProps.largeStep, this.orientation = X.defaultProps.orientation, this.disabled = X.defaultProps.disabled, this.thumbAlignment = X.defaultProps.thumbAlignment
    }
    static {
        this.tagName = `media-volume-slider`
    }
    static {
        this.properties = {
            label: {
                type: String
            },
            step: {
                type: Number
            },
            largeStep: {
                type: Number,
                attribute: `large-step`
            },
            orientation: {
                type: String
            },
            disabled: {
                type: Boolean
            },
            thumbAlignment: {
                type: String,
                attribute: `thumb-alignment`
            }
        }
    }
    #e = new X;
    #t = new F(this, {
        context: $
    });
    #n = new B(this, I, Xe);
    #r = null;
    #i = null;
    connectedCallback() {
        if (super.connectedCallback(), this.destroyed) return;
        this.#i = new AbortController;
        let e = this.#i.signal;
        this.#r = st({
            getElement: () => this,
            getThumbElement: () => this.querySelector(`media-slider-thumb`),
            getOrientation: () => this.orientation,
            isRTL: () => ce(this),
            isDisabled: () => this.disabled || !this.#n.value,
            getPercent: () => {
                let e = this.#n.value;
                return e ? e.volume * 100 : 0
            },
            getStepPercent: () => this.#e.getStepPercent(),
            getLargeStepPercent: () => this.#e.getLargeStepPercent(),
            onValueChange: e => {
                this.#a(e)
            },
            onValueCommit: e => {
                this.#a(e)
            },
            onDragStart: () => {
                this.dispatchEvent(new CustomEvent(`drag-start`, {
                    bubbles: !0
                }))
            },
            onDragEnd: () => {
                this.dispatchEvent(new CustomEvent(`drag-end`, {
                    bubbles: !0
                }))
            },
            adjustPercent: (e, t, n) => this.#e.adjustPercentForAlignment(e, t, n),
            onResize: () => this.requestUpdate()
        }), j(this, this.#r.rootProps, {
            signal: e
        }), T(this, this.#r.rootStyle), this.#r.input.subscribe(() => this.requestUpdate(), {
            signal: e
        })
    }
    disconnectedCallback() {
        super.disconnectedCallback(), this.#i?.abort(), this.#i = null
    }
    destroyCallback() {
        this.#r?.destroy(), super.destroyCallback()
    }
    willUpdate(e) {
        super.willUpdate(e), this.#e.setProps(this)
    }
    update(e) {
        if (super.update(e), !this.#r) return;
        let t = this.#n.value;
        if (!t) return;
        this.#e.setInput(this.#r.input.current), this.#e.setMedia(t);
        let n = this.#e.getState(),
            r = ct(this.#r.adjustForAlignment(n));
        T(this, r), M(this, n, G), this.#t.setValue({
            state: n,
            stateAttrMap: G,
            pointerValue: this.#e.valueFromPercent(n.pointerPercent),
            thumbAttrs: this.#e.getAttrs(n),
            thumbProps: this.#r.thumbProps,
            formatValue: e => `${Math.round(e)}%`
        })
    }
    #a(e) {
        this.#n.value?.setVolume(this.#e.valueFromPercent(e) / 100)
    }
}), V(Pn), V(Fn), V(In), V(zn), V(Bn);

function Hn() {
    return `<media-container class="media-default-skin media-default-skin--video"><slot name="media"></slot><media-buffering-indicator class="media-buffering-indicator"><div class="media-surface"> ${H(`spinner`, { class: `media-icon` })} </div></media-buffering-indicator><media-controls class="media-surface media-controls"><media-tooltip-group><media-play-button commandfor="play-tooltip" class="media-button media-button--icon media-button--play"> ${H(`restart`, { class: `media-icon media-icon--restart` })} ${H(`play`, { class: `media-icon media-icon--play` })} ${H(`pause`, { class: `media-icon media-icon--pause` })} </media-play-button><media-tooltip id="play-tooltip" side="top" class="media-surface media-tooltip"><span class="media-tooltip-label media-tooltip-label--replay">Replay</span><span class="media-tooltip-label media-tooltip-label--play">Play</span><span class="media-tooltip-label media-tooltip-label--pause">Pause</span></media-tooltip><media-seek-button commandfor="seek-backward-tooltip" seconds="-10" class="media-button media-button--icon media-button--seek"><span class="media-icon__container"> ${H(`seek`, { class: `media-icon media-icon--flipped` })} <span class="media-icon__label">10</span></span></media-seek-button><media-tooltip id="seek-backward-tooltip" side="top" class="media-surface media-tooltip"> Seek backward 10 seconds </media-tooltip><media-seek-button commandfor="seek-forward-tooltip" seconds="10" class="media-button media-button--icon media-button--seek"><span class="media-icon__container"> ${H(`seek`, { class: `media-icon` })} <span class="media-icon__label">10</span></span></media-seek-button><media-tooltip id="seek-forward-tooltip" side="top" class="media-surface media-tooltip"> Seek forward 10 seconds </media-tooltip><media-time-group class="media-time"><media-time type="current" class="media-time__value"></media-time><media-time-slider class="media-slider"><media-slider-track class="media-slider__track"><media-slider-fill class="media-slider__fill"></media-slider-fill><media-slider-buffer class="media-slider__buffer"></media-slider-buffer></media-slider-track><media-slider-thumb class="media-slider__thumb"></media-slider-thumb><div class="media-surface media-preview media-slider__preview"><media-slider-thumbnail class="media-preview__thumbnail"></media-slider-thumbnail><media-slider-value type="pointer" class="media-preview__timestamp"></media-slider-value> ${H(`spinner`, { class: `media-preview__spinner media-icon` })} </div></media-time-slider><media-time type="duration" class="media-time__value"></media-time></media-time-group><media-playback-rate-button commandfor="playback-rate-tooltip" class="media-button media-button--icon media-button--playback-rate"></media-playback-rate-button><media-tooltip id="playback-rate-tooltip" side="top" class="media-surface media-tooltip"> Toggle playback rate </media-tooltip><media-mute-button commandfor="video-volume-popover" class="media-button media-button--icon media-button--mute"> ${H(`volume-off`, { class: `media-icon media-icon--volume-off` })} ${H(`volume-low`, { class: `media-icon media-icon--volume-low` })} ${H(`volume-high`, { class: `media-icon media-icon--volume-high` })} </media-mute-button><media-popover id="video-volume-popover" open-on-hover delay="200" close-delay="100" side="top" class="media-surface media-popover media-popover--volume"><media-volume-slider class="media-slider" orientation="vertical" thumb-alignment="edge"><media-slider-track class="media-slider__track"><media-slider-fill class="media-slider__fill"></media-slider-fill></media-slider-track><media-slider-thumb class="media-slider__thumb media-slider__thumb--persistent"></media-slider-thumb></media-volume-slider></media-popover><media-captions-button commandfor="captions-tooltip" class="media-button media-button--icon media-button--captions"> ${H(`captions-off`, { class: `media-icon media-icon--captions-off` })} ${H(`captions-on`, { class: `media-icon media-icon--captions-on` })} </media-captions-button><media-tooltip id="captions-tooltip" side="top" class="media-surface media-tooltip"><span class="media-tooltip-label media-tooltip-label--enable-captions">Enable captions</span><span class="media-tooltip-label media-tooltip-label--disable-captions">Disable captions</span></media-tooltip><media-pip-button commandfor="pip-tooltip" class="media-button media-button--icon media-button--pip"> ${H(`pip`, { class: `media-icon` })} </media-pip-button><media-tooltip id="pip-tooltip" side="top" class="media-surface media-tooltip"><span class="media-tooltip-label media-tooltip-label--enter-pip">Enter picture-in-picture</span><span class="media-tooltip-label media-tooltip-label--exit-pip">Exit picture-in-picture</span></media-tooltip><media-fullscreen-button commandfor="fullscreen-tooltip" class="media-button media-button--icon media-button--fullscreen"> ${H(`fullscreen-enter`, { class: `media-icon media-icon--fullscreen-enter` })} ${H(`fullscreen-exit`, { class: `media-icon media-icon--fullscreen-exit` })} </media-fullscreen-button><media-tooltip id="fullscreen-tooltip" side="top" class="media-surface media-tooltip"><span class="media-tooltip-label media-tooltip-label--enter-fullscreen">Enter fullscreen</span><span class="media-tooltip-label media-tooltip-label--exit-fullscreen">Exit fullscreen</span></media-tooltip></media-tooltip-group></media-controls><div class="media-overlay"></div></media-container>`
}
var Un = class extends Vt(Dt) {
    static {
        this.tagName = `video-skin`
    }
    static {
        this.styles = Ht(Ut)
    }
    static {
        this.getTemplateHTML = Hn
    }
};
customElements.define(Un.tagName, Un);
//# sourceMappingURL=video.js.map