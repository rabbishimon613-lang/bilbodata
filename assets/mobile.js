/* ============================================================
   Bilbo Data — mobile experience layer
   Builds the small-screen nav sheet from whatever nav the page
   already has, and makes wide tables scroll instead of blowing
   out the page. No page-specific markup required.
   ============================================================ */
(function(){
  function init(){
    var header=document.querySelector("header");
    var wrap=header&&header.querySelector(".wrap");
    var nav=header&&header.querySelector("nav.tabs");
    if(!header||!wrap) return wideTables();

    /* ---- burger ---- */
    var burger=document.createElement("button");
    burger.className="m-burger";burger.type="button";
    burger.setAttribute("aria-label","Menu");burger.setAttribute("aria-expanded","false");
    burger.innerHTML="<i></i><i></i><i></i>";
    wrap.appendChild(burger);

    /* ---- sheet, mirrored from the page's own nav ---- */
    var sheet=document.createElement("div");
    sheet.className="m-sheet";
    var scrim=document.createElement("div");
    scrim.className="m-scrim";

    var items=nav?[].slice.call(nav.children):[];
    items.forEach(function(src){
      var b=document.createElement("button");
      b.type="button";
      b.className="m-item"+(src.classList.contains("on")?" on":"");
      b.textContent=(src.textContent||"").trim();
      b.addEventListener("click",function(){
        close();
        /* replay the click on the real control so page logic still owns it */
        if(src.tagName==="A"&&src.getAttribute("href")&&!src.dataset.tab){location.href=src.href;}
        else src.click();
      });
      sheet.appendChild(b);
    });

    var whois=header.querySelector(".whois");
    if(whois){
      var cta=document.createElement("button");
      cta.type="button";cta.className="m-cta";cta.textContent=whois.textContent.trim()||"Who's You?";
      cta.addEventListener("click",function(){close();whois.click();});
      sheet.appendChild(cta);
    }
    var mark=header.querySelector(".mark");
    if(mark){
      var m=document.createElement("div");
      m.className="m-mark";m.textContent=mark.textContent.trim();
      sheet.appendChild(m);
    }

    document.body.appendChild(scrim);
    document.body.appendChild(sheet);

    function open(){sheet.classList.add("on");scrim.classList.add("on");burger.classList.add("on");
      burger.setAttribute("aria-expanded","true");document.body.classList.add("m-locked");}
    function close(){sheet.classList.remove("on");scrim.classList.remove("on");burger.classList.remove("on");
      burger.setAttribute("aria-expanded","false");document.body.classList.remove("m-locked");}
    burger.addEventListener("click",function(){sheet.classList.contains("on")?close():open();});
    scrim.addEventListener("click",close);
    addEventListener("keydown",function(e){if(e.key==="Escape")close();});
    addEventListener("resize",function(){if(innerWidth>980)close();});

    wideTables();
  }

  /* wide tables get their own scroller so the page never scrolls sideways */
  function wideTables(){
    [].forEach.call(document.querySelectorAll("table"),function(t){
      if(t.closest(".m-tablescroll")||t.closest(".tablewrap"))return;
      var s=document.createElement("div");s.className="m-tablescroll";
      t.parentNode.insertBefore(s,t);s.appendChild(t);
    });
  }

  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);
  else init();
  /* pages that build tables later */
  addEventListener("load",wideTables);
})();
