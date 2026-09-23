
(function(){
  "use strict";
  const reduce=window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function toast(message, ms){
    if(!message) return;
    const el=document.createElement("div");
    el.className="cf-toast";
    el.setAttribute("role","status");
    el.textContent=message;
    document.body.appendChild(el);
    setTimeout(()=>{el.classList.add("cf-out");setTimeout(()=>el.remove(),260)}, ms||2800);
  }
  window.CampusFindToast=toast;

  function loading(on){
    let ov=document.querySelector(".cf-loading-overlay");
    if(on){
      if(!ov){
        ov=document.createElement("div");
        ov.className="cf-loading-overlay";
        ov.innerHTML='<div class="cf-spinner" aria-label="Loading"></div>';
        document.body.appendChild(ov);
      }
    }else if(ov){ov.remove();}
  }
  window.CampusFindLoading=loading;

  document.addEventListener("DOMContentLoaded",function(){
    // Smooth reveal for common content blocks
    const selectors=".card,.item-card,.lost-card,.found-card,.feature-card,.stat-card,.post-card,.container-card";
    document.querySelectorAll(selectors).forEach((el,i)=>{
      el.classList.add("cf-reveal");
      if(reduce){el.classList.add("cf-visible");}
      else setTimeout(()=>el.classList.add("cf-visible"),Math.min(i*45,450));
    });

    // Loading feedback for form submits without changing form behavior
    document.querySelectorAll("form").forEach(form=>{
      form.addEventListener("submit",function(e){
        if(e.defaultPrevented) return;
        const submit=e.submitter || form.querySelector('button[type="submit"],input[type="submit"]');
        if(submit && submit.dataset.noLoading==="true") return;
        setTimeout(()=>loading(true),20);
      });
    });

    // Image preview for file inputs
    document.querySelectorAll('input[type="file"]').forEach(input=>{
      input.addEventListener("change",function(){
        const file=this.files && this.files[0];
        if(!file || !file.type.startsWith("image/")) return;
        let preview=document.querySelector("#cf-image-preview");
        if(!preview){
          preview=document.createElement("img");
          preview.id="cf-image-preview";
          preview.style.cssText="display:block;max-width:180px;max-height:140px;object-fit:cover;border-radius:14px;margin-top:10px;box-shadow:0 8px 20px rgba(0,0,0,.12)";
          this.parentNode.appendChild(preview);
        }
        const reader=new FileReader();
        reader.onload=()=>preview.src=reader.result;
        reader.readAsDataURL(file);
      });
    });

    // Friendly confirmation for destructive actions
    document.querySelectorAll('[data-confirm]').forEach(el=>{
      el.addEventListener("click",function(e){
        if(!window.confirm(this.dataset.confirm)) e.preventDefault();
      });
    });
  });

  window.addEventListener("pageshow",()=>loading(false));
})();
