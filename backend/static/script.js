document.addEventListener('DOMContentLoaded', () => {
    const elements = {
        qpUpload: document.getElementById('qp-upload'),
        qpBox: document.getElementById('qp-box'),
        qpInfo: document.getElementById('qp-info'),
        extractQpBtn: document.getElementById('extract-qp-btn'),
        btnIconQp: document.getElementById('btn-icon-qp'),
        btnTextQp: document.getElementById('btn-text-qp'),
        qpResultContainer: document.getElementById('qp-result-container'),
        qpResultText: document.getElementById('qp-result-text'),

        generateRubricsBtn: document.getElementById('generate-rubrics-btn'),
        btnIconRubrics: document.getElementById('btn-icon-rubrics'),
        btnTextRubrics: document.getElementById('btn-text-rubrics'),
        rubricsResultContainer: document.getElementById('rubrics-result-container'),
        rubricsResultText: document.getElementById('rubrics-result-text'),

        asUpload: document.getElementById('as-upload'),
        asBox: document.getElementById('as-box'),
        asInfo: document.getElementById('as-info'),
        extractAsBtn: document.getElementById('extract-as-btn'),
        btnIconAs: document.getElementById('btn-icon-as'),
        btnTextAs: document.getElementById('btn-text-as'),
        asResultContainer: document.getElementById('as-result-container'),
        asResultText: document.getElementById('as-result-text'),

        evaluateBtn: document.getElementById('evaluate-btn'),
        btnIconEval: document.getElementById('btn-icon-eval'),
        btnTextEval: document.getElementById('btn-text-eval'),
        evaluationNote: document.getElementById('evaluation-note'),

        errorContainer: document.getElementById('error-container'),
        errorText: document.getElementById('error-text'),
        resultsContainer: document.getElementById('results-container'),
        resultsList: document.getElementById('results-list'),
        emptyState: document.getElementById('empty-state'),

        examTitle: document.getElementById('exam-title'),
        examSummary: document.getElementById('exam-summary'),
        refreshStatusBtn: document.getElementById('refresh-status-btn'),
        newExamBtn: document.getElementById('new-exam-btn'),

        statusQuestion: document.getElementById('status-question'),
        statusQuestionCopy: document.getElementById('status-question-copy'),
        statusRubrics: document.getElementById('status-rubrics'),
        statusRubricsCopy: document.getElementById('status-rubrics-copy'),
        statusAnswer: document.getElementById('status-answer'),
        statusAnswerCopy: document.getElementById('status-answer-copy'),
    };

    let questionPaperFile = null;
    let answerSheetFile = null;
    let qpSegments = [];
    let finalMappedResults = [];

    if (elements.qpUpload) {
        elements.qpUpload.addEventListener('change', (e) => {
            questionPaperFile = e.target.files[0] || null;
            if (!questionPaperFile) {
                setUploadSelection(elements.qpInfo, elements.qpBox, 'PDF or image', false);
                return;
            }
            setUploadSelection(elements.qpInfo, elements.qpBox, questionPaperFile.name, true);
        });
    }

    if (elements.asUpload) {
        elements.asUpload.addEventListener('change', (e) => {
            answerSheetFile = e.target.files[0] || null;
            if (!answerSheetFile) {
                setUploadSelection(elements.asInfo, elements.asBox, 'Handwritten or typed', false);
                if (elements.extractAsBtn) {
                    elements.extractAsBtn.disabled = true;
                }
                return;
            }
            setUploadSelection(elements.asInfo, elements.asBox, answerSheetFile.name, true);
            if (elements.extractAsBtn && qpSegments.length > 0) {
                elements.extractAsBtn.disabled = false;
            }
        });
    }

    if (elements.refreshStatusBtn) {
        elements.refreshStatusBtn.addEventListener('click', loadExamStatus);
    }

    if (elements.newExamBtn) {
        elements.newExamBtn.addEventListener('click', () => {
            const workflowPanel = document.getElementById('workflow-panel');
            if (workflowPanel) {
                workflowPanel.scrollIntoView({ behavior: 'smooth' });
            } else {
                window.location.href = '/upload-answer-papers';
            }
        });
    }

    if (elements.extractQpBtn) {
        elements.extractQpBtn.addEventListener('click', async () => {
            if (!questionPaperFile) {
                showError('Please select a question paper file first.');
                return;
            }

            clearError();
            setLoadingState(elements.extractQpBtn, elements.btnIconQp, elements.btnTextQp, 'loader-2', 'Extracting Question Paper...');

            try {
                const qpResponse = await processDocument(questionPaperFile, 'question');
                const parsed = JSON.parse(qpResponse);
                qpSegments = parsed.segments || [];

                reveal(elements.qpResultContainer);
                if (elements.qpResultText) {
                    elements.qpResultText.textContent = JSON.stringify(parsed, null, 2);
                }

                if (elements.generateRubricsBtn) {
                    elements.generateRubricsBtn.disabled = false;
                }
                if (elements.asUpload && answerSheetFile && elements.extractAsBtn) {
                    elements.extractAsBtn.disabled = false;
                }

                setCompletedState(elements.btnIconQp, elements.btnTextQp, 'Question Paper Extracted');
                await loadExamStatus();
            } catch (error) {
                console.error(error);
                showError(error.message || 'Failed to extract question paper.');
                resetButtonState(elements.extractQpBtn, elements.btnIconQp, elements.btnTextQp, 'file-text', 'Extract Question Paper');
            } finally {
                elements.extractQpBtn.disabled = false;
            }
        });
    }

    if (elements.generateRubricsBtn) {
        elements.generateRubricsBtn.addEventListener('click', async () => {
            clearError();
            setLoadingState(elements.generateRubricsBtn, elements.btnIconRubrics, elements.btnTextRubrics, 'loader-2', 'Generating Rubrics...');

            try {
                const response = await fetch('/generate-rubrics', { method: 'POST' });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.error || 'Failed to generate rubrics.');
                }

                reveal(elements.rubricsResultContainer);
                if (elements.rubricsResultText) {
                    elements.rubricsResultText.textContent = JSON.stringify(data.rubrics, null, 2);
                }

                setCompletedState(elements.btnIconRubrics, elements.btnTextRubrics, 'Rubrics Generated');
                await loadExamStatus();
            } catch (error) {
                console.error(error);
                showError(error.message || 'An error occurred during rubric generation.');
                resetButtonState(elements.generateRubricsBtn, elements.btnIconRubrics, elements.btnTextRubrics, 'sparkles', 'Generate Rubrics');
            } finally {
                elements.generateRubricsBtn.disabled = false;
            }
        });
    }

    if (elements.extractAsBtn) {
        elements.extractAsBtn.addEventListener('click', async () => {
            if (!answerSheetFile) {
                showError('Please select an answer script file.');
                return;
            }
            if (qpSegments.length === 0) {
                showError('Extract the question paper first so the backend has question IDs.');
                return;
            }

            clearError();
            hide(elements.resultsContainer);
            hide(elements.emptyState);
            if (elements.evaluateBtn) {
                elements.evaluateBtn.disabled = true;
            }
            if (elements.evaluationNote) {
                elements.evaluationNote.textContent = 'Mapping in progress...';
            }
            setLoadingState(elements.extractAsBtn, elements.btnIconAs, elements.btnTextAs, 'loader-2', 'Extracting And Mapping...');

            try {
                const asResponse = await processDocument(answerSheetFile, 'answer');
                reveal(elements.asResultContainer);
                if (elements.asResultText) {
                    try {
                        const parsed = JSON.parse(asResponse);
                        elements.asResultText.textContent = JSON.stringify(parsed, null, 2);
                    } catch (_error) {
                        elements.asResultText.textContent = asResponse;
                    }
                }

                const ids = qpSegments.map((question) => question.id);
                const answersList = await fetchApi('/extract-answers', { text: asResponse, ids });

                finalMappedResults = qpSegments.map((question) => {
                    const match = (answersList || []).find((answer) =>
                        String(answer.id).trim().toLowerCase() === String(question.id).trim().toLowerCase()
                    );
                    return {
                        id: question.id,
                        section: question.section,
                        question: buildQuestionLabel(question),
                        answer: match ? match.answer : 'Not found in student script'
                    };
                });

                if (elements.evaluateBtn) {
                    elements.evaluateBtn.disabled = false;
                }
                if (elements.evaluationNote) {
                    elements.evaluationNote.textContent = 'Mapped answers are ready for evaluation.';
                }
                setCompletedState(elements.btnIconAs, elements.btnTextAs, 'Mapping Complete');
                await loadExamStatus();
            } catch (error) {
                console.error(error);
                showError(error.message || 'Failed to process answer script.');
                resetButtonState(elements.extractAsBtn, elements.btnIconAs, elements.btnTextAs, 'scan-text', 'Extract And Map');
                if (elements.evaluationNote) {
                    elements.evaluationNote.textContent = 'Evaluation becomes available after answer mapping completes.';
                }
            } finally {
                elements.extractAsBtn.disabled = false;
            }
        });
    }

    if (elements.evaluateBtn) {
        elements.evaluateBtn.addEventListener('click', async () => {
            if (finalMappedResults.length === 0) {
                showError('No mapped answers are available to evaluate.');
                return;
            }

            clearError();
            hide(elements.resultsContainer);
            hide(elements.emptyState);
            setLoadingState(elements.evaluateBtn, elements.btnIconEval, elements.btnTextEval, 'loader-2', 'Evaluating Answers...');

            try {
                const evaluatedResults = await fetchApi('/evaluate-answers', { mapped_results: finalMappedResults });
                renderResults(evaluatedResults);
                setCompletedState(elements.btnIconEval, elements.btnTextEval, 'Evaluation Complete');
            } catch (error) {
                console.error(error);
                showError(error.message || 'Failed to evaluate answers.');
                resetButtonState(elements.evaluateBtn, elements.btnIconEval, elements.btnTextEval, 'graduation-cap', 'Evaluate Answers');
            } finally {
                elements.evaluateBtn.disabled = false;
            }
        });
    }

    async function loadExamStatus() {
        const hasStatusTargets = elements.examTitle || elements.statusQuestion || elements.generateRubricsBtn;
        if (!hasStatusTargets) {
            return;
        }

        try {
            const response = await fetch('/exam-status');
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.error || 'Failed to load exam status.');
            }

            qpSegments = data.question_segments || qpSegments;
            const exam = data.exam || {};

            if (elements.examTitle) {
                elements.examTitle.textContent = exam.title || 'No exam created';
            }
            if (elements.examSummary) {
                elements.examSummary.textContent = buildExamSummary(exam);
            }

            setStatusCard(elements.statusQuestion, elements.statusQuestionCopy, data.has_question_paper, 'Ready', exam.question_count ? `${exam.question_count} questions extracted.` : 'No file processed yet.');
            setStatusCard(elements.statusRubrics, elements.statusRubricsCopy, data.has_rubrics, 'Ready', data.has_rubrics ? `${data.summary.rubric_count} rubric items available.` : 'Generate after extracting questions.');
            setStatusCard(elements.statusAnswer, elements.statusAnswerCopy, data.has_answer_script, 'Ready', data.has_answer_script ? `${data.summary.mapped_answer_count} mapped answers found.` : 'Upload a script to map answers.');

            if (elements.generateRubricsBtn && data.has_question_paper) {
                elements.generateRubricsBtn.disabled = false;
            }
            if (elements.extractAsBtn && answerSheetFile && qpSegments.length > 0) {
                elements.extractAsBtn.disabled = false;
            }
        } catch (error) {
            console.error(error);
            showError(error.message || 'Unable to load exam status.');
        }
    }

    async function processDocument(file, type) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('type', type);

        const response = await fetch('/process-document', {
            method: 'POST',
            body: formData
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Server error');
        }
        return data.text;
    }

    async function fetchApi(endpoint, body) {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'API call failed.');
        }
        return data;
    }

    function renderResults(results) {
        if (!elements.resultsList) {
            return;
        }

        elements.resultsList.innerHTML = '';
        if (!results || results.length === 0) {
            reveal(elements.emptyState);
            return;
        }

        results.forEach((item) => {
            const card = document.createElement('article');
            card.className = 'result-card';

            const feedbackHtml = item.score !== undefined ? `
                <div class="evaluation-box">
                    <div class="evaluation-box__head">
                        <span>Evaluation</span>
                        <strong>Score: ${escapeHtml(String(item.score))}</strong>
                    </div>
                    <p>${escapeHtml(item.feedback || '')}</p>
                </div>
            ` : '';

            card.innerHTML = `
                <div class="result-card__head">
                    <span class="result-chip">Question ${escapeHtml(String(item.id))}</span>
                    <span class="result-section">${item.section ? `Section ${escapeHtml(String(item.section))}` : 'Unsectioned'}</span>
                </div>
                <h4>${escapeHtml(item.question || '')}</h4>
                <div class="answer-box">
                    <span>Student Answer</span>
                    <p class="${item.answer && item.answer.includes('Not found') ? 'is-muted' : ''}">${escapeHtml(item.answer || '')}</p>
                </div>
                ${feedbackHtml}
            `;
            elements.resultsList.appendChild(card);
        });

        reveal(elements.resultsContainer);
        lucide.createIcons();
    }

    function buildQuestionLabel(question) {
        const text = question.text || question.question || 'Untitled question';
        return question.marks ? `${text} [${question.marks}]` : text;
    }

    function buildExamSummary(exam) {
        if (!exam || !exam.question_count) {
            return 'Upload a question paper to create the first exam.';
        }

        const parts = [];
        if (exam.subject) {
            parts.push(exam.subject);
        }
        parts.push(`${exam.question_count} questions`);
        if (exam.total_marks !== undefined && exam.total_marks !== null) {
            parts.push(`${exam.total_marks} marks`);
        }
        return parts.join(' - ');
    }

    function setStatusCard(titleEl, copyEl, isReady, readyLabel, description) {
        if (!titleEl || !copyEl) {
            return;
        }
        titleEl.textContent = isReady ? readyLabel : 'Pending';
        titleEl.dataset.state = isReady ? 'ready' : 'pending';
        copyEl.textContent = description;
    }

    function setLoadingState(button, iconEl, textEl, iconName, label) {
        if (!button || !iconEl || !textEl) {
            return;
        }
        button.disabled = true;
        iconEl.setAttribute('data-lucide', iconName);
        iconEl.classList.add('animate-spin');
        textEl.textContent = label;
        lucide.createIcons();
    }

    function setCompletedState(iconEl, textEl, label) {
        if (!iconEl || !textEl) {
            return;
        }
        iconEl.setAttribute('data-lucide', 'check-circle');
        iconEl.classList.remove('animate-spin');
        textEl.textContent = label;
        lucide.createIcons();
    }

    function resetButtonState(button, iconEl, textEl, iconName, label) {
        if (!button || !iconEl || !textEl) {
            return;
        }
        button.disabled = false;
        iconEl.setAttribute('data-lucide', iconName);
        iconEl.classList.remove('animate-spin');
        textEl.textContent = label;
        lucide.createIcons();
    }

    function setUploadSelection(infoEl, boxEl, label, active) {
        if (infoEl) {
            infoEl.textContent = label;
        }
        if (boxEl) {
            boxEl.classList.toggle('active', active);
        }
    }

    function showError(message) {
        if (!elements.errorContainer || !elements.errorText) {
            return;
        }
        elements.errorText.textContent = message;
        elements.errorContainer.classList.remove('hidden');
    }

    function clearError() {
        if (elements.errorContainer) {
            elements.errorContainer.classList.add('hidden');
        }
    }

    function reveal(node) {
        if (node) {
            node.classList.remove('hidden');
        }
    }

    function hide(node) {
        if (node) {
            node.classList.add('hidden');
        }
    }

    window.downloadContent = (elementId, filename) => {
        const node = document.getElementById(elementId);
        if (!node) {
            return;
        }
        const blob = new Blob([node.textContent], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = filename;
        anchor.click();
        URL.revokeObjectURL(url);
    };

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    loadExamStatus();
});
