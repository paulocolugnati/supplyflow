// EN: Behavior of the logged-in app and access screens (formatting, counter and theme come
//     from sf.js). Every feature is an enhancement: without JavaScript the pages still work,
//     and the server re-checks everything.
//     1. confirm before submitting forms marked with data-confirm
//     2. copy buttons (data-copy="#input")
//     3. sign-up: show fields for the chosen account type + live rack-tag preview
//     4. onboarding: live discount ruler while the owner types
//     5. <details> menus close on outside click and Escape
//     6. counters roll in on load (data-contador-rolar)
//     7. dismissable notices
// PT: Comportamento do sistema logado e das telas de acesso (formatação, contador e tema vêm
//     do sf.js). Todo recurso é um extra: sem JavaScript as páginas continuam funcionando, e
//     o servidor confere tudo de novo.
//     1. confirmação antes de enviar formulários marcados com data-confirm
//     2. botões de copiar (data-copy="#campo")
//     3. cadastro: mostra os campos do tipo de conta escolhido + prévia ao vivo da etiqueta
//     4. onboarding: régua de desconto ao vivo enquanto o dono digita
//     5. menus <details> fecham ao clicar fora e no Esc
//     6. contadores giram ao carregar (data-contador-rolar)
//     7. avisos que podem ser fechados
(function () {
    'use strict';

    // EN: 1. Confirmation | PT: 1. Confirmação
    document.addEventListener('submit', function (event) {
        const message = event.target.dataset.confirm;
        if (message && !window.confirm(message)) {
            event.preventDefault();
        }
    });


    // EN: 2. Copy | PT: 2. Copiar
    document.addEventListener('click', function (event) {
        const button = event.target.closest('[data-copy]');
        if (!button) {
            return;
        }
        const input = document.querySelector(button.dataset.copy);
        if (!input) {
            return;
        }
        input.select();
        navigator.clipboard.writeText(input.value).then(function () {
            const label = button.querySelector('span') || button;
            const original = label.textContent;
            label.textContent = '✓';
            setTimeout(function () { label.textContent = original; }, 1500);
        });
    });


    // EN: 3. Sign-up | PT: 3. Cadastro
    const typeRadios = document.querySelectorAll('input[name="account_type"]');

    function updateAccountType() {
        const checked = document.querySelector('input[name="account_type"]:checked');
        const value = checked ? checked.value : '';
        document.querySelectorAll('[data-show-when]').forEach(function (element) {
            element.hidden = element.dataset.showWhen !== value;
        });
    }

    if (typeRadios.length) {
        typeRadios.forEach(function (radio) { radio.addEventListener('change', updateAccountType); });
        updateAccountType();
    }

    const nameInput = document.querySelector('[data-previa-nome]');
    const nameTarget = document.querySelector('[data-previa-alvo]');
    if (nameInput && nameTarget) {
        nameInput.addEventListener('input', function () {
            nameTarget.textContent = nameInput.value.trim() || nameTarget.dataset.previaVazio;
        });
    }


    // EN: 4. Onboarding live ruler. Same parsing rule as parse_percent in helpers.py
    //        ("12,5" or "12.5"); invalid input leaves the ruler as it was.
    // PT: 4. Régua ao vivo do onboarding. Mesma regra do parse_percent do helpers.py
    //        ("12,5" ou "12.5"); entrada inválida deixa a régua como estava.
    const onboardingForm = document.querySelector('[data-onboarding]');
    const liveRuler = document.querySelector('[data-regua-viva]');

    function percentToBps(text) {
        const clean = (text || '').trim().replace('%', '');
        if (!/^\d{1,3}([.,]\d{1,2})?$/.test(clean)) {
            return null;
        }
        const parts = clean.replace(',', '.').split('.');
        const bps = parseInt(parts[0], 10) * 100 + parseInt((parts[1] || '').padEnd(2, '0') || '0', 10);
        return bps <= 10000 ? bps : null;
    }

    function updateLiveRuler() {
        const seller = percentToBps(onboardingForm.elements.member_limit.value);
        const manager = percentToBps(onboardingForm.elements.admin_limit.value);
        const margin = percentToBps(onboardingForm.elements.min_margin.value);
        if (seller !== null && manager !== null && seller <= manager) {
            // EN: the scale grows in steps of 5% so the manager stop always fits
            // PT: a escala cresce de 5 em 5% para o batente do gerente sempre caber
            const scale = manager <= 1500 ? 20 : (Math.floor(manager / 500) + 1) * 5;
            liveRuler.style.setProperty('--escala', scale);
            liveRuler.style.setProperty('--vendedor', seller / 100);
            liveRuler.style.setProperty('--gerente', manager / 100);
            document.querySelector('[data-regua-valor="vendedor"]').textContent = window.SF.formatPercent(seller);
            document.querySelector('[data-regua-valor="gerente"]').textContent = window.SF.formatPercent(manager);
        }
        if (margin !== null) {
            document.querySelector('[data-regua-valor="margem"]').textContent = window.SF.formatPercent(margin);
        }
    }

    if (onboardingForm && liveRuler) {
        onboardingForm.addEventListener('input', updateLiveRuler);
    }


    // EN: 5. Menus | PT: 5. Menus
    document.addEventListener('click', function (event) {
        document.querySelectorAll('details.menu[open]').forEach(function (menu) {
            if (!menu.contains(event.target)) {
                menu.removeAttribute('open');
            }
        });
    });
    document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') {
            return;
        }
        document.querySelectorAll('details.menu[open]').forEach(function (menu) {
            menu.removeAttribute('open');
            const summary = menu.querySelector('summary');
            if (summary) {
                summary.focus();
            }
        });
    });


    // EN: 6. Counters | PT: 6. Contadores
    document.querySelectorAll('[data-contador-rolar]').forEach(function (el) {
        window.SF.rollIn(el);
    });


    // EN: 8. Product form: cost in R$ or %, with a live preview of cost and margin.
    //       Same parsing rules as parse_money / parse_percent in helpers.py.
    // PT: 8. Formulário de produto: custo em R$ ou %, com prévia ao vivo do custo e da margem.
    //       Mesmas regras do parse_money / parse_percent do helpers.py.
    function moneyToCents(text) {
        let clean = (text || '').replace('R$', '').replace(/\s/g, '');
        if (!clean) {
            return null;
        }
        if (clean.includes(',') && clean.includes('.')) {
            clean = clean.lastIndexOf(',') > clean.lastIndexOf('.')
                ? clean.replace(/\./g, '').replace(',', '.')
                : clean.replace(/,/g, '');
        } else if (clean.includes(',')) {
            clean = clean.replace(',', '.');
        } else if (/^\d{1,3}(\.\d{3})+$/.test(clean)) {
            clean = clean.replace(/\./g, '');
        }
        if (!/^\d{1,9}(\.\d{1,2})?$/.test(clean)) {
            return null;
        }
        const parts = clean.split('.');
        return parseInt(parts[0], 10) * 100 + parseInt((parts[1] || '').padEnd(2, '0') || '0', 10);
    }

    const productForm = document.querySelector('[data-produto]');

    function updateProductPreview() {
        const price = moneyToCents(productForm.querySelector('[data-preco]').value);
        const modeInput = productForm.querySelector('[data-modo-custo]:checked');
        const costText = productForm.querySelector('[data-custo]').value;
        const costOut = productForm.querySelector('[data-previa-custo]');
        const marginOut = productForm.querySelector('[data-previa-margem-valor]');
        let cost = null;
        if (costText.trim()) {
            if (modeInput && modeInput.value === 'pct') {
                const bps = percentToBps(costText);
                cost = bps !== null && price ? Math.floor((price * bps + 5000) / 10000) : null;
            } else {
                cost = moneyToCents(costText);
            }
        }
        costOut.textContent = cost !== null ? window.SF.formatMoney(cost) : '—';
        if (cost !== null && price) {
            const margin = Math.floor(((price - cost) * 10000) / price);
            marginOut.textContent = (margin < 0 ? '-' : '') + window.SF.formatPercent(Math.abs(margin));
            marginOut.classList.toggle('margem-negativa', margin < 0);
        } else {
            marginOut.textContent = '—';
        }
    }

    if (productForm) {
        productForm.addEventListener('input', updateProductPreview);
        productForm.addEventListener('change', function (event) {
            // EN: switching R$ <-> % changes the placeholder | PT: trocar R$ <-> % muda o placeholder
            if (event.target.matches('[data-modo-custo]')) {
                productForm.querySelector('[data-custo]').placeholder = event.target.value === 'pct' ? '0' : '0,00';
            }
            updateProductPreview();
        });
        updateProductPreview();
    }


    // EN: 9. Opportunity form: only the chosen customer's contacts are offered
    // PT: 9. Formulário de oportunidade: só os contatos do cliente escolhido aparecem
    const customerSelect = document.querySelector('[data-cliente]');
    const contactSelect = document.querySelector('[data-contato]');

    function filterContacts() {
        const company = customerSelect.value;
        Array.from(contactSelect.options).forEach(function (option) {
            if (!option.dataset.empresa) {
                return;
            }
            option.hidden = option.dataset.empresa !== company;
            if (option.hidden && option.selected) {
                contactSelect.value = '';
            }
        });
    }

    if (customerSelect && contactSelect) {
        customerSelect.addEventListener('change', filterContacts);
        filterContacts();
    }


    // EN: 10. Quote builder: live totals with the same rules as pricing.py (integer cents
    //        and basis points, rounding half away from zero). Only a preview: the server
    //        recalculates everything when the form is saved.
    // PT: 10. Montador de orçamento: totais ao vivo com as mesmas regras do pricing.py
    //        (centavos e basis points inteiros, arredondando o meio para longe do zero). É só
    //        uma prévia: o servidor recalcula tudo quando o formulário é salvo.
    function roundDiv(numerator, denominator) {
        const sign = numerator < 0 ? -1 : 1;
        return sign * Math.floor((Math.abs(numerator) * 2 + denominator) / (denominator * 2));
    }

    function applyDiscount(cents, bps) {
        return roundDiv(cents * (10000 - bps), 10000);
    }

    const quoteForm = document.querySelector('[data-orcamento]');
    const totals = document.querySelector('[data-totais]');

    function updateQuote() {
        const rows = Array.from(quoteForm.querySelectorAll('[data-item]'));
        let subtotal = 0;
        let listTotal = 0;
        let costedLines = 0;
        let costedCost = 0;
        let costed = false;
        let valid = true;

        rows.forEach(function (row) {
            const price = parseInt(row.dataset.preco, 10);
            const quantity = parseInt(row.querySelector('[data-quantidade]').value, 10);
            const discountText = row.querySelector('[data-desconto]').value.trim();
            const discount = discountText === '' ? 0 : percentToBps(discountText);
            if (!(quantity >= 1) || discount === null) {
                valid = false;
                return;
            }
            const line = applyDiscount(price * quantity, discount);
            row.querySelector('[data-linha-total]').textContent = window.SF.formatMoney(line);
            subtotal += line;
            listTotal += price * quantity;
            if (row.dataset.custo !== '') {
                costed = true;
                costedLines += line;
                costedCost += parseInt(row.dataset.custo, 10) * quantity;
            }
        });

        const headerText = quoteForm.querySelector('[data-desconto-geral]').value.trim();
        const header = headerText === '' ? 0 : percentToBps(headerText);
        if (!valid || header === null) {
            return;
        }

        const final = applyDiscount(subtotal, header);
        const effective = listTotal ? roundDiv((listTotal - final) * 10000, listTotal) : 0;
        window.SF.setCounter(totals.querySelector('[data-total="tabela"]'), window.SF.formatMoney(listTotal));
        window.SF.setCounter(totals.querySelector('[data-total="final"]'), window.SF.formatMoney(final));
        window.SF.setCounter(totals.querySelector('[data-total="desconto"]'), window.SF.formatPercent(effective));

        const marginEl = totals.querySelector('[data-total="margem"]');
        const costedFinal = applyDiscount(costedLines, header);
        if (costed && costedFinal > 0) {
            const margin = roundDiv((costedFinal - costedCost) * 10000, costedFinal);
            const text = (margin < 0 ? '-' : '') + window.SF.formatPercent(Math.abs(margin));
            window.SF.setCounter(marginEl, text);
            marginEl.classList.toggle('margem-negativa', margin < 0);
        }

        // EN: move the pointer on the ruler | PT: move o ponteiro na régua
        const ruler = totals.querySelector('[data-regua-orcamento]');
        const scale = parseFloat(getComputedStyle(ruler).getPropertyValue('--escala')) || 20;
        ruler.style.setProperty('--ponteiro', Math.min(effective / 100, scale));

        const notice = quoteForm.querySelector('[data-aviso-alterado]');
        if (notice) {
            notice.hidden = false;
        }
        // EN: finishing uses the SAVED quote, so with unsaved edits we ask to save first
        // PT: concluir usa o orçamento SALVO, então com edições não salvas pedimos para salvar antes
        document.querySelectorAll('[data-concluir] button[type="submit"]').forEach(function (button) {
            button.disabled = true;
        });
        document.querySelectorAll('[data-salvar-antes]').forEach(function (hint) {
            hint.hidden = false;
        });
    }

    if (quoteForm && totals && quoteForm.querySelector('[data-desconto-geral]')) {
        quoteForm.addEventListener('input', updateQuote);
        // EN: counters start from the saved values without animation
        // PT: os contadores começam dos valores salvos, sem animação
        totals.querySelectorAll('[data-total]').forEach(function (el) {
            window.SF.setCounter(el, el.textContent.trim());
        });
    }


    // EN: 11. Quote draft kept on this device. Every change is copied to localStorage; when the
    //        page opens with values different from the copy (the save never reached the
    //        server), it offers to restore them. When the saved page matches the copy, the
    //        copy is dropped. Storage can be blocked (private mode): then nothing happens.
    // PT: 11. Rascunho do orçamento guardado neste aparelho. Toda mudança vai para o
    //        localStorage; quando a página abre com valores diferentes da cópia (o salvamento
    //        não chegou ao servidor), oferece restaurar. Quando a página salva bate com a
    //        cópia, a cópia é apagada. O armazenamento pode estar bloqueado (aba anônima):
    //        aí nada acontece.
    const draftForm = document.querySelector('[data-rascunho]');
    const draftNotice = document.querySelector('[data-rascunho-aviso]');

    function draftFields() {
        return Array.from(draftForm.elements).filter(function (el) {
            return el.name && el.name !== '_csrf' && el.type !== 'submit';
        });
    }

    function draftSnapshot() {
        const values = {};
        draftFields().forEach(function (el) { values[el.name] = el.value; });
        return values;
    }

    function sameValues(a, b) {
        return Object.keys(a).every(function (key) { return !(key in b) || a[key] === b[key]; });
    }

    function readDraft(key) {
        try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch (error) { return null; }
    }

    function writeDraft(key, value) {
        try {
            if (value === null) { localStorage.removeItem(key); } else { localStorage.setItem(key, JSON.stringify(value)); }
        } catch (error) { /* EN: storage blocked | PT: armazenamento bloqueado */ }
    }

    if (draftForm && draftNotice) {
        const key = draftForm.dataset.rascunho;
        const saved = readDraft(key);
        if (saved && saved.values) {
            if (sameValues(saved.values, draftSnapshot())) {
                writeDraft(key, null);
            } else {
                const time = new Date(saved.at);
                const label = String(time.getHours()).padStart(2, '0') + ':' + String(time.getMinutes()).padStart(2, '0');
                const text = draftNotice.querySelector('[data-rascunho-texto]');
                text.textContent = text.dataset.modelo.replace('{time}', label);
                draftNotice.hidden = false;
            }
        }

        let timer = null;
        draftForm.addEventListener('input', function () {
            clearTimeout(timer);
            timer = setTimeout(function () { writeDraft(key, { at: Date.now(), values: draftSnapshot() }); }, 300);
        });

        draftNotice.querySelector('[data-rascunho-restaurar]').addEventListener('click', function () {
            const values = (readDraft(key) || {}).values || {};
            draftFields().forEach(function (el) {
                if (el.name in values) { el.value = values[el.name]; }
            });
            draftNotice.hidden = true;
            // EN: recalculate the live totals and keep the copy | PT: recalcula os totais ao vivo e mantém a cópia
            draftForm.dispatchEvent(new Event('input', { bubbles: true }));
        });

        draftNotice.querySelector('[data-rascunho-descartar]').addEventListener('click', function () {
            writeDraft(key, null);
            draftNotice.hidden = true;
        });
    }


    // EN: 12. Pipeline drag and drop (mouse). Dropping a card fills the hidden form and posts it,
    //        exactly like the arrow menu, so the server rules decide (manual win needs a value,
    //        a seller only moves their own cards...). A lost stage asks for an optional reason.
    //        Touch screens and keyboards keep using the arrow menu.
    // PT: 12. Arrastar e soltar no funil (mouse). Soltar um cartão preenche o formulário
    //        escondido e envia, igual ao menu da seta, então quem decide são as regras do
    //        servidor (ganho manual exige valor, vendedor só move os próprios cartões...).
    //        Uma etapa perdida pede um motivo opcional. Toque e teclado continuam com o menu.
    const moveForm = document.querySelector('[data-mover-form]');
    let draggedCard = null;

    if (moveForm) {
        document.querySelectorAll('[data-cartao]').forEach(function (card) {
            card.addEventListener('dragstart', function (event) {
                draggedCard = card;
                card.classList.add('arrastando');
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/plain', card.dataset.cartao);
            });
            card.addEventListener('dragend', function () {
                card.classList.remove('arrastando');
                document.querySelectorAll('.alvo-soltar').forEach(function (el) { el.classList.remove('alvo-soltar'); });
                draggedCard = null;
            });
        });

        document.querySelectorAll('[data-etapa]').forEach(function (column) {
            column.addEventListener('dragover', function (event) {
                if (!draggedCard || draggedCard.parentElement === column) { return; }
                event.preventDefault();
                column.classList.add('alvo-soltar');
            });
            column.addEventListener('dragleave', function (event) {
                if (!column.contains(event.relatedTarget)) { column.classList.remove('alvo-soltar'); }
            });
            column.addEventListener('drop', function (event) {
                event.preventDefault();
                column.classList.remove('alvo-soltar');
                if (!draggedCard || draggedCard.parentElement === column) { return; }
                let reason = '';
                if (column.dataset.tipo === 'lost') {
                    const question = document.querySelector('[data-mover-modelo]').dataset.moverModelo;
                    reason = window.prompt(question, '');
                    if (reason === null) { return; }
                }
                moveForm.action = '/opportunities/' + draggedCard.dataset.cartao + '/stage';
                moveForm.elements.stage_id.value = column.dataset.etapa;
                moveForm.elements.lost_reason.value = reason;
                moveForm.submit();
            });
        });
    }


    // EN: 7. Notices | PT: 7. Avisos
    document.addEventListener('click', function (event) {
        const button = event.target.closest('[data-fechar-aviso]');
        if (button) {
            button.closest('.aviso').remove();
        }
    });
})();
