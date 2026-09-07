(() => {
  const menu=document.getElementById('menu'), sidebar=document.getElementById('sidebar');
  const loader=document.getElementById('loadingScreen'), progress=document.getElementById('pageProgress');
  if(menu&&sidebar) menu.addEventListener('click',()=>{sidebar.classList.toggle('show');document.body.classList.toggle('menu-open',sidebar.classList.contains('show'));});
  const hideLoader=()=>{if(!loader)return;loader.classList.add('loaded');setTimeout(()=>loader.remove(),520);};
  window.addEventListener('load',()=>setTimeout(hideLoader,650)); setTimeout(hideLoader,2300);
  document.addEventListener('click',e=>{
    const link=e.target.closest('a'); if(!link||!link.href||link.target==='_blank'||link.hasAttribute('download')||link.href.startsWith('javascript:'))return;
    const url=new URL(link.href,location.href); if(url.origin!==location.origin||url.hash&&url.pathname===location.pathname)return;
    e.preventDefault(); if(progress)progress.classList.add('active'); document.body.classList.add('page-leaving');
    setTimeout(()=>location.href=url.href,160);
  });
  document.querySelectorAll('form').forEach(form=>form.addEventListener('submit',()=>{
    const button=form.querySelector('button[type="submit"]');
    if(button&&!button.dataset.loading){button.dataset.loading='1';button.disabled=true;button.classList.add('is-loading');button.innerHTML='<span class="button-spinner"></span> Please wait…';}
    if(progress)progress.classList.add('active');
  }));
  setTimeout(()=>document.querySelectorAll('.toast').forEach(x=>{x.classList.add('toast-hide');setTimeout(()=>x.remove(),350)}),4500);
  const items=document.querySelectorAll('.reveal,.item-card');
  if('IntersectionObserver' in window){const io=new IntersectionObserver((entries,obs)=>entries.forEach(en=>{if(en.isIntersecting){en.target.classList.add('in-view');obs.unobserve(en.target)}}),{threshold:.08});items.forEach(x=>io.observe(x));}
})();
