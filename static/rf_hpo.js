let rfChart = null;
let rfParetoChart = null;
let rfLastResult = null;
const rfColors = {'Baseline':'#d49b49','Grid Search':'#c0504d','Random Search':'#4f81bd','Bayesian (TPE)':'#2e8b57'};

function rfNumber(value, digits=4) {
    return value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString('vi-VN',{maximumFractionDigits:digits});
}

function rfRender(result) {
    rfLastResult = result;
    $('rf-result').hidden = false;
    $('rf-result-caption').textContent = `${result.data.source} · ${Number(result.data.rows).toLocaleString('vi-VN')} dòng · ${result.data.features} đặc trưng · nhãn ${result.data.target} · ${result.settings.budget} cấu hình/phương pháp · ${result.settings.seeds} seed · 5-fold CV`;
    $('rf-data-info').textContent = `Tỷ lệ nhãn 1: ${(result.data.positive_rate*100).toFixed(2)}%. Dữ liệu dùng để so sánh: một tập train/CV và một tập test độc lập.`;
    $('rf-summary').innerHTML = result.summary.map(row => `<tr class="${row.method==='Baseline'?'winner':''}"><td><b>${escapeHtml(row.method)}</b></td><td>${rfNumber(row.cv_auc_mean)} ± ${rfNumber(row.cv_auc_std)}</td><td>${rfNumber(row.test_auc_mean)}</td><td>${rfNumber(row.test_ap_mean)}</td><td>${row.wall_time_s_mean==null?'—':rfNumber(row.wall_time_s_mean,2)+' giây'}</td><td>${row.inference_ms_per_1000_mean==null?'—':rfNumber(row.inference_ms_per_1000_mean,2)+' ms'}</td><td>${row.evaluations_to_best_mean==null?'—':rfNumber(row.evaluations_to_best_mean,1)}</td><td>${row.evaluations_to_99pct_mean==null?'—':rfNumber(row.evaluations_to_99pct_mean,1)}</td></tr>`).join('');
    const best = result.best_runs;
    $('rf-best-runs').innerHTML = `<table><thead><tr><th>Phương pháp</th><th>Seed</th><th>AUC CV</th><th>AUC test</th><th>Cấu hình tốt nhất</th></tr></thead><tbody>${best.map(row=>`<tr><td>${escapeHtml(row.method)}</td><td>${row.seed}</td><td>${rfNumber(row.cv_auc)}</td><td>${rfNumber(row.test_auc)}</td><td>n=${row.best_n}; depth=${row.best_d}; split=${row.best_ms}; leaf=${row.best_ml}; features=${escapeHtml(row.best_mf)}</td></tr>`).join('')}</tbody></table>`;
    $('rf-stat-test').textContent = result.friedman_p_value==null ? 'Kiểm định Friedman cần ít nhất 3 seed; hãy tăng số seed nếu cần đánh giá khác biệt thống kê.' : `Kiểm định Friedman giữa ba phương pháp trên AUC CV: p = ${rfNumber(result.friedman_p_value,5)} (${result.friedman_p_value<0.05?'có':'chưa có'} bằng chứng khác biệt ở mức 5%).`;
    $('rf-trials').innerHTML = result.trials.map(row=>`<tr><td>${escapeHtml(row.method)}</td><td>${row.seed}</td><td>${row.evaluation}</td><td>${rfNumber(row.cv_auc)}</td><td>${row.n??'—'}</td><td>${row.d??'—'}</td><td>${row.ms??'—'}</td><td>${row.ml??'—'}</td><td>${escapeHtml(row.mf??'—')}</td></tr>`).join('');
    if (rfChart) rfChart.destroy();
    if (window.Chart) rfChart = new Chart($('rf-chart'),{type:'line',data:{datasets:['Grid Search','Random Search','Bayesian (TPE)'].map(method=>({label:method,data:result.convergence.filter(row=>row.method===method).map(row=>({x:row.evaluation,y:row.mean_best_auc})),borderColor:rfColors[method],backgroundColor:rfColors[method],pointRadius:1,borderWidth:2,tension:.15}))},options:{responsive:true,maintainAspectRatio:false,animation:false,scales:{x:{type:'linear',title:{display:true,text:'Số cấu hình đã đánh giá'}},y:{min:0,max:1,title:{display:true,text:'AUC CV tốt nhất tới thời điểm đó'}}},plugins:{legend:{labels:{boxWidth:12}}}}});
    $('rf-sensitivity').innerHTML=result.sensitivity.map(row=>`<tr><td>${escapeHtml(row.parameter)}</td><td>${rfNumber(row.spearman_with_cv_auc)}</td></tr>`).join('');
    $('rf-worst').innerHTML=result.worst_trials.map(row=>`<tr><td>${escapeHtml(row.method)}</td><td>${row.seed}</td><td>${row.evaluation}</td><td>${rfNumber(row.cv_auc)}</td><td>${row.n}</td><td>${row.d}</td><td>${escapeHtml(row.mf)}</td></tr>`).join('');
    if(rfParetoChart)rfParetoChart.destroy();if(window.Chart)rfParetoChart=new Chart($('rf-pareto-chart'),{type:'scatter',data:{datasets:[{label:'Phương pháp theo seed',data:result.pareto_front.map(row=>({x:row.inference_ms_per_1000,y:row.cv_auc,label:`${row.method} · seed ${row.seed}`})),backgroundColor:'#137557'}]},options:{responsive:true,maintainAspectRatio:false,scales:{x:{title:{display:true,text:'Độ trễ (ms / 1.000 mẫu)'}},y:{min:0,max:1,title:{display:true,text:'AUC CV'}}},plugins:{tooltip:{callbacks:{label:ctx=>`${ctx.raw.label}: ${ctx.raw.y.toFixed(4)} AUC · ${ctx.raw.x.toFixed(2)} ms`}}}}});
}

function rfCsv(rows) {
    const columns = [...new Set(rows.flatMap(row=>Object.keys(row)))];
    const cell = value => `"${String(value??'').replaceAll('"','""')}"`;
    return '\ufeff'+[columns.map(cell).join(','),...rows.map(row=>columns.map(key=>cell(row[key])).join(','))].join('\r\n');
}

$('rf-hpo-form').onsubmit = safely(async event => {
    event.preventDefault();
    $('rf-start').disabled=true;$('rf-result').hidden=true;$('rf-error').textContent='';$('rf-progress').value=0;$('rf-status').textContent='Đang gửi yêu cầu…';$('rf-progress-label').textContent='';
    const form=new FormData();
    for(const [key,id] of [['target','rf-target'],['rows','rf-rows'],['budget','rf-budget'],['seeds','rf-seeds'],['n_max','rf-nmax']])form.append(key,$(id).value);
    const file=$('rf-dataset').files[0];if(file)form.append('dataset',file);
    try {
        const start=await fetch('/api/rf-hpo',{method:'POST',headers:{'X-CSRF-Token':window.csrfToken||''},body:form});
        const started=await start.json();if(!start.ok)throw Error(started.error||'Không thể bắt đầu thí nghiệm.');
        let finished=false;
        while(!finished){
            await new Promise(resolve=>setTimeout(resolve,1000));
            const response=await api('/rf-hpo/'+started.id);const job=await response;
            $('rf-status').textContent=job.stage||job.status;
            $('rf-progress').max=job.total||1;$('rf-progress').value=job.done||0;
            $('rf-progress-label').textContent=`${job.done||0} / ${job.total||0} lượt đánh giá đã xong`;
            if(job.status==='failed')throw Error(job.error||'Thí nghiệm không hoàn tất.');
            if(job.status==='completed'){rfRender(job.result);$('rf-status').textContent='Đã hoàn tất.';finished=true;}
        }
    } catch(error) {
        $('rf-error').textContent=error.message||'Có lỗi khi chạy thí nghiệm.';
        $('rf-status').textContent='Thí nghiệm bị dừng.';
    } finally { $('rf-start').disabled=false; }
});

$('rf-download').onclick=()=>{
    if(!rfLastResult)return;
    const rows=[...rfLastResult.baseline_runs.map(row=>({record_type:'baseline',method:'Baseline',...row})),...rfLastResult.trials.map(row=>({record_type:'trial',...row})),...rfLastResult.best_runs.map(row=>({record_type:'best',...row}))];
    const url=URL.createObjectURL(new Blob([rfCsv(rows)],{type:'text/csv;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download='rf-hpo-ket-qua.csv';link.click();URL.revokeObjectURL(url);
};
