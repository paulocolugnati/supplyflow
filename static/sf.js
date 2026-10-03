// EN: SupplyFlow shared behavior, used by the landing page and the logged-in app:
//     1. number formatting with integer math (cents and basis points)
//     2. the mechanical counter (signature): digits roll like an odometer
//     3. the theme switch (dark default, light option, remembered in a cookie)
//     Exposed as window.SF so page scripts (landing.js, app.js) can use it.
// PT: Comportamento compartilhado do SupplyFlow, usado pela página inicial e pelo sistema:
//     1. formatação de números com conta inteira (centavos e basis points)
//     2. o contador mecânico (assinatura): os dígitos giram como um odômetro
//     3. a troca de tema (escuro padrão, opção clara, lembrada num cookie)
//     Exposto como window.SF para os scripts de página (landing.js, app.js) usarem.
(function () {
    'use strict';

    const root = document.documentElement;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;


    // -----------------------------------------------------------------
    // EN: 1. Formatting | PT: 1. Formatação
    // -----------------------------------------------------------------

    function groupThousands(text, separator) {
        return text.replace(/\B(?=(\d{3})+(?!\d))/g, separator);
    }

    // EN: Money is always in the Brazilian format (the currency is the real), in both
    //     languages, exactly like the server's brl filter: R$ 1.234,56
    // PT: Dinheiro sempre no formato brasileiro (a moeda é o real), nos dois idiomas,
    //     igual ao filtro brl do servidor: R$ 1.234,56
    function formatMoney(cents) {
        const reais = Math.floor(cents / 100);
        const centavos = String(cents % 100).padStart(2, '0');
        return 'R$ ' + groupThousands(String(reais), '.') + ',' + centavos;
    }

    // EN: Same rule as the server's pct filter: 1250 -> '12,5%', 500 -> '5%'
    // PT: Mesma regra do filtro pct do servidor: 1250 -> '12,5%', 500 -> '5%'
    function formatPercent(bps) {
        const whole = Math.floor(bps / 100);
        const fraction = bps % 100;
        if (fraction === 0) {
            return whole + '%';
        }
        return whole + ',' + String(fraction).padStart(2, '0').replace(/0$/, '') + '%';
    }


    // -----------------------------------------------------------------
    // EN: 2. Mechanical counter. Each digit becomes a strip 0-9 that slides to its value;
    //        separators stay still; screen readers get the plain text via aria-label.
    // PT: 2. Contador mecânico. Cada dígito vira uma fita de 0 a 9 que desliza até o valor;
    //        separadores ficam parados; leitores de tela recebem o texto puro via aria-label.
    // -----------------------------------------------------------------

    function maskOf(text) {
        return text.replace(/\d/g, '0');
    }

    function buildCounter(el, text) {
        el.textContent = '';
        el.dataset.mascara = maskOf(text);
        const wheels = [];
        Array.from(text).forEach(function (char) {
            if (/\d/.test(char)) {
                const wheel = document.createElement('span');
                wheel.className = 'contador-roda';
                const strip = document.createElement('span');
                strip.className = 'contador-fita';
                for (let digit = 0; digit <= 9; digit++) {
                    const cell = document.createElement('span');
                    cell.textContent = String(digit);
                    strip.appendChild(cell);
                }
                wheel.appendChild(strip);
                el.appendChild(wheel);
                wheels.push(strip);
            } else {
                const still = document.createElement('span');
                still.textContent = char;
                el.appendChild(still);
            }
        });
        // EN: the rightmost digit moves first, like gears | PT: o dígito da direita gira primeiro, como engrenagens
        wheels.slice().reverse().forEach(function (strip, index) {
            strip.style.setProperty('--atraso', (index * 45) + 'ms');
        });
        el.contadorFitas = wheels;
        Array.from(el.children).forEach(function (child) { child.setAttribute('aria-hidden', 'true'); });
    }

    function setCounter(el, text) {
        if (el.dataset.valor === text) {
            return;
        }
        if (!el.contadorFitas || el.dataset.mascara !== maskOf(text)) {
            buildCounter(el, text);
        }
        const digits = text.replace(/\D/g, '');
        el.contadorFitas.forEach(function (strip, index) {
            strip.style.setProperty('--digito', digits[index]);
        });
        el.dataset.valor = text;
        el.setAttribute('aria-label', text);
    }

    // EN: Roll a counter from zeros up to its server-rendered text (used on page load)
    // PT: Gira um contador de zeros até o texto que veio do servidor (usado ao carregar a página)
    function rollIn(el) {
        const target = (el.dataset.alvo || el.textContent).trim();
        if (reduced) {
            setCounter(el, target);
            return;
        }
        setCounter(el, target.replace(/\d/g, '0'));
        requestAnimationFrame(function () {
            requestAnimationFrame(function () { setCounter(el, target); });
        });
    }


    // EN: "Download PDF" opens the browser's print dialog (Save as PDF). No inline script: the
    //     page's CSP only runs scripts from files
    // PT: "Baixar PDF" abre a janela de impressão do navegador (Salvar como PDF). Sem script
    //     embutido: a CSP da página só roda scripts de arquivos
    document.addEventListener('click', function (event) {
        if (event.target.closest('[data-imprimir]')) {
            window.print();
        }
    });


    // -----------------------------------------------------------------
    // EN: 3. Theme switch | PT: 3. Troca de tema
    // -----------------------------------------------------------------

    document.addEventListener('click', function (event) {
        const button = event.target.closest('[data-tema-botao]');
        if (!button) {
            return;
        }
        const next = root.dataset.theme === 'light' ? 'dark' : 'light';
        root.dataset.theme = next;
        document.querySelectorAll('[data-tema-botao]').forEach(function (b) {
            b.setAttribute('aria-pressed', next === 'light' ? 'true' : 'false');
        });
        // EN: one year; Flask reads it so the next page paints in the right theme
        // PT: um ano; o Flask lê o cookie para a próxima página já vir no tema certo
        document.cookie = 'theme=' + next + '; path=/; max-age=31536000; samesite=lax';
        const meta = document.querySelector('meta[name="theme-color"]');
        if (meta) {
            meta.content = next === 'light' ? '#F4F8F7' : '#0B2A33';
        }
    });


    window.SF = {
        reduced: reduced,
        formatMoney: formatMoney,
        formatPercent: formatPercent,
        setCounter: setCounter,
        rollIn: rollIn,
    };
})();
