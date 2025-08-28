(function(){
  const cvs = document.getElementById('canvas');
  const ctx = cvs.getContext('2d');
  const img = new Image();

  const scalePts = []; // [{x,y}, {x,y}]
  let dragging = false;
  let roi = null; // {x,y,w,h}
  let dragStart = null;

  const $scale = document.getElementById('scale_cm');
  const $reset = document.getElementById('resetBtn');
  const $process = document.getElementById('processBtn');
  const $result = document.getElementById('result');

  function draw(){
    ctx.clearRect(0,0,cvs.width,cvs.height);
    ctx.drawImage(img, 0, 0, cvs.width, cvs.height);

    // scale points
    ctx.fillStyle = 'red';
    scalePts.forEach(p => {
      ctx.beginPath();
      ctx.arc(p.x, p.y, 4, 0, Math.PI*2);
      ctx.fill();
    });
    if(scalePts.length === 2){
      ctx.beginPath();
      ctx.moveTo(scalePts[0].x, scalePts[0].y);
      ctx.lineTo(scalePts[1].x, scalePts[1].y);
      ctx.strokeStyle = 'red';
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    // roi
    if(roi){
      ctx.strokeStyle = 'deepskyblue';
      ctx.lineWidth = 2;
      ctx.strokeRect(roi.x, roi.y, roi.w, roi.h);
    }
  }

  img.onload = function(){
    cvs.width = img.width;
    cvs.height = img.height;
    draw();
  };
  img.src = IMG_URL;

  cvs.addEventListener('click', e => {
    const rect = cvs.getBoundingClientRect();
    const x = e.clientX - rect.left; 
    const y = e.clientY - rect.top;
    if(scalePts.length < 2){
      scalePts.push({x,y});
      draw();
    }
  });

  cvs.addEventListener('mousedown', e => {
    const rect = cvs.getBoundingClientRect();
    dragStart = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    dragging = true;
  });
  cvs.addEventListener('mousemove', e => {
    if(!dragging) return;
    const rect = cvs.getBoundingClientRect();
    const x = e.clientX - rect.left; 
    const y = e.clientY - rect.top;
    roi = { x: Math.min(dragStart.x, x), y: Math.min(dragStart.y, y),
            w: Math.abs(x - dragStart.x), h: Math.abs(y - dragStart.y) };
    draw();
  });
  cvs.addEventListener('mouseup', () => { dragging = false; });
  cvs.addEventListener('mouseleave', () => { dragging = false; });

  $reset.addEventListener('click', () => {
    scalePts.length = 0; 
    roi = null; 
    draw();
  });

  $process.addEventListener('click', async () => {
    if(scalePts.length !== 2){
      alert('請先在影像上點兩點作為比例尺');
      return;
    }
    if(!roi || roi.w < 2 || roi.h < 2){
      alert('請拖曳滑鼠畫出 ROI');
      return;
    }
    const payload = {
      job_id: JOB_ID,
      scale_cm: parseFloat($scale.value),
      p1: scalePts[0],
      p2: scalePts[1],
      bbox: roi
    };
    $result.classList.remove('hidden');
    $result.innerHTML = '<p>Processing... 這可能需要一小段時間，請勿關閉頁面。</p>';

    try{
      const res = await fetch('/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if(!data.ok){
        throw new Error(data.error || '伺服器錯誤');
      }
      $result.innerHTML = `
        <p>✅ 完成！</p>
        <p><a href="${data.video_url}">下載處理後影片</a></p>
        <p><a href="${data.csv_url}">下載 CSV</a></p>
      `;
    } catch(err){
      console.error(err);
      $result.innerHTML = `<p>❌ 失敗：${err.message || '請重試或更換影片。'}</p>`;
    }
  });
})();
