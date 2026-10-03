// EN: Landing page behavior that belongs only to SupplyFlow (the sites-incriveis engine in
//     static/fx is never edited; custom behavior lives here):
//     2. address rail: pointer follows the scroll, current address is marked
//     3. plan prices rolling in the mechanical counter
//     4. the peak: the margin lock, driven by the pinned scene's --progresso
//     5. the reorder lane, drawn when it enters the screen
//     (1. theme switch and the counter itself live in sf.js, shared with the app)
// PT: Comportamento da página inicial que é só do SupplyFlow (o motor sites-incriveis em
//     static/fx nunca é editado; o comportamento próprio fica aqui):
//     2. trilho de endereços: o ponteiro segue a rolagem e o endereço atual é marcado
//     3. preços dos planos girando no contador mecânico
//     4. o pico: a trava da margem, movida pelo --progresso da cena presa
//     5. a faixa de recompra, desenhada quando entra na tela
//     (1. troca de tema e o contador em si ficam no sf.js, compartilhado com o sistema)
(function () {
    'use strict';

    const reduced = window.SF.reduced;


    // EN: Formatting and the mechanical counter come from sf.js (shared with the app)
    // PT: Formatação e contador mecânico vêm do sf.js (compartilhado com o sistema)
    const formatMoney = window.SF.formatMoney;
    const formatPercent = window.SF.formatPercent;
    const setCounter = window.SF.setCounter;


    // -----------------------------------------------------------------
    // EN: 2. Address rail | PT: 2. Trilho de endereços
    // -----------------------------------------------------------------

    const rail = document.querySelector('.trilho');
    const railLinks = Array.from(document.querySelectorAll('[data-endereco]'));

    function updateRail() {
        const max = document.documentElement.scrollHeight - window.innerHeight;
        const progress = max > 0 ? Math.min(1, Math.max(0, window.scrollY / max)) : 0;
        if (rail) {
            rail.style.setProperty('--rail', progress.toFixed(4));
        }
    }

    // EN: The address whose scene crosses the middle of the screen is "current"
    // PT: O endereço cuja cena cruza o meio da tela é o "atual"
    if ('IntersectionObserver' in window && railLinks.length) {
        const byId = new Map(railLinks.map(function (link) { return [link.dataset.endereco, link]; }));
        const observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) {
                    return;
                }
                railLinks.forEach(function (link) { link.removeAttribute('aria-current'); });
                const link = byId.get(entry.target.id);
                if (link) {
                    link.setAttribute('aria-current', 'true');
                }
            });
        }, { rootMargin: '-45% 0px -50% 0px' });
        byId.forEach(function (link, id) {
            const scene = document.getElementById(id);
            if (scene) {
                observer.observe(scene);
            }
        });
    }


    // -----------------------------------------------------------------
    // EN: 3. Plan prices | PT: 3. Preços dos planos
    // -----------------------------------------------------------------

    // EN: Plan prices roll from zero when they enter the screen
    // PT: Os preços dos planos giram a partir do zero quando entram na tela
    const priceCounters = Array.from(document.querySelectorAll('[data-contador-entrada]'));
    priceCounters.forEach(function (el) {
        const target = formatMoney(parseInt(el.dataset.contadorEntrada, 10));
        if (reduced) {
            setCounter(el, target);
            return;
        }
        setCounter(el, target.replace(/\d/g, '0'));
        el.dataset.alvo = target;
    });
    if (!reduced && 'IntersectionObserver' in window) {
        const priceObserver = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    setCounter(entry.target, entry.target.dataset.alvo);
                    priceObserver.unobserve(entry.target);
                }
            });
        }, { threshold: 0.6 });
        priceCounters.forEach(function (el) { priceObserver.observe(el); });
    }


    // -----------------------------------------------------------------
    // EN: 4. The peak: margin lock | PT: 4. O pico: a trava da margem
    //     EN: Example quote (fictional): list price R$ 1.800,00, cost R$ 1.376,00.
    //         Seller ceiling 5%, manager ceiling 15% (the product's defaults).
    //     PT: Orçamento de exemplo (fictício): preço de tabela R$ 1.800,00, custo R$ 1.376,00.
    //         Teto do vendedor 5%, do gerente 15% (os padrões do produto).
    // -----------------------------------------------------------------

    const LIST_CENTS = 180000;
    const COST_CENTS = 137600;
    const SELLER_CEILING = 500;

    const lock = document.getElementById('trava');

    function finalCents(bps) {
        // EN: integer rounding, half up | PT: arredondamento inteiro, meio para cima
        return Math.floor((LIST_CENTS * (10000 - bps) + 5000) / 10000);
    }

    function marginBps(total) {
        return Math.floor(((total - COST_CENTS) * 10000 + Math.floor(total / 2)) / total);
    }

    function stepAt(progress) {
        // EN: Returns [discount in bps, state, narration step] for a scroll position
        // PT: Devolve [desconto em bps, estado, passo da narração] para uma posição da rolagem
        if (progress < 0.10) {
            return [0, 'rascunho', 1];
        }
        if (progress < 0.34) {
            const ramp = (progress - 0.10) / 0.24;
            const bps = Math.round((ramp * 800) / 25) * 25;
            return bps > SELLER_CEILING ? [bps, 'aguardando', 2] : [bps, 'rascunho', 1];
        }
        if (progress < 0.48) {
            return [800, 'aguardando', 2];
        }
        if (progress < 0.62) {
            return [800, 'aprovado', 3];
        }
        if (progress < 0.76) {
            return [900, 'caiu', 4];
        }
        if (progress < 0.88) {
            return [800, 'enviado', 5];
        }
        return [800, 'aceito', 5];
    }

    function renderLock(progress) {
        const [bps, state, step] = stepAt(progress);
        const total = finalCents(bps);

        lock.style.setProperty('--ponteiro', (bps / 100).toFixed(2));
        lock.dataset.travado = bps > SELLER_CEILING && (state === 'aguardando' || state === 'caiu') ? '5' : '';
        lock.dataset.passo = String(step);

        lock.querySelectorAll('[data-contador]').forEach(function (el) {
            const kind = el.dataset.contador;
            if (kind === 'desconto' || kind === 'ponteiro') {
                setCounter(el, formatPercent(bps));
            } else if (kind === 'margem') {
                setCounter(el, formatPercent(marginBps(total)));
            } else if (kind === 'total') {
                setCounter(el, formatMoney(total));
            }
        });

        const stateBox = lock.querySelector('.estado');
        const stateText = lock.querySelector('[data-estado-texto]');
        if (stateBox.dataset.estado !== state) {
            stateBox.dataset.estado = state;
            stateText.textContent = stateText.dataset['txt' + state.charAt(0).toUpperCase() + state.slice(1)] || stateText.textContent;
        }

        lock.querySelectorAll('[data-passo-item]').forEach(function (item) {
            const n = parseInt(item.dataset.passoItem, 10);
            item.classList.toggle('ativo', n === step);
            item.classList.toggle('feito', n < step);
        });
    }

    let lastProgress = -1;

    function updateLock() {
        if (!lock) {
            return;
        }
        // EN: Same formula the engine uses for --progresso, computed here so we never read a
        //     value from the previous frame
        // PT: Mesma fórmula que o motor usa no --progresso, calculada aqui para nunca ler um
        //     valor do quadro anterior
        const travel = lock.offsetHeight - window.innerHeight;
        const top = lock.getBoundingClientRect().top;
        const value = travel > 0 ? Math.min(1, Math.max(0, -top / travel)) : 0;
        if (value !== lastProgress) {
            lastProgress = value;
            renderLock(value);
        }
    }

    if (lock) {
        if (reduced) {
            // EN: Still page: show the approved, accepted end state and every step
            // PT: Página parada: mostra o estado final aprovado e aceito, e todos os passos
            renderLock(0.95);
            lock.querySelectorAll('[data-passo-item]').forEach(function (item) { item.classList.add('ativo'); });
        } else {
            renderLock(0);
        }
    }


    // -----------------------------------------------------------------
    // EN: 5. Reorder lane | PT: 5. Faixa de recompra
    // -----------------------------------------------------------------

    const orders = document.querySelector('[data-pedidos]');
    if (orders) {
        if (reduced || !('IntersectionObserver' in window)) {
            orders.classList.add('desenhar');
        } else {
            const orderObserver = new IntersectionObserver(function (entries) {
                if (entries[0].isIntersecting) {
                    orders.classList.add('desenhar');
                    orderObserver.disconnect();
                }
            }, { threshold: 0.35 });
            orderObserver.observe(orders);
        }
    }


    // -----------------------------------------------------------------
    // EN: Scroll loop: one requestAnimationFrame per scroll burst
    // PT: Laço de rolagem: um requestAnimationFrame por rajada de rolagem
    // -----------------------------------------------------------------

    let scheduled = false;

    function onScroll() {
        if (scheduled) {
            return;
        }
        scheduled = true;
        requestAnimationFrame(function () {
            scheduled = false;
            updateRail();
            if (!reduced) {
                updateLock();
            }
        });
    }

    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    onScroll();
})();
