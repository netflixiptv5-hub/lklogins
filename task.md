# PX CAPTCHA Solver Task

## Key Finding from Latest Test (x52cok169usmns0vk8r)
- The `#px-captcha` div inside the iframe has **size 0x0** in all scans!
- `<DIV> id=px-captcha cls= aria= role= tab=0 size=0x0 pos=(0,0)`
- But the PARENT page's evaluation shows `px-captcha box: {x:780, y:670, w:360, h:42}`
- This means there are TWO #px-captcha elements:
  1. One on the main page (inside a nested iframe) — size 360x42
  2. One inside the hsprotect iframe — size 0x0

## The Real Problem
The `#px-captcha` inside the hsprotect iframe is the "control" div (size 0x0).
The VISIBLE captcha (bar + icon) is rendered by the PX JavaScript in a **nested iframe** 
inside the first #px-captcha div. Look at the HTML:
```
<div id="px-captcha" style="display:block; min-width:275px;">
  <iframe style="display:none; width:100%; height:42px; ..." title="Human verification challenge">
  </iframe>
</div>
```
The inner iframe has `display:none` — PX toggles it visible via JS.

## The accessibility icon issue
- Our coordinate clicks target (735,691) area — LEFT of the px-captcha box
- But ALL clicks return height=0 from the frame check — because we're checking the WRONG frame
- The clicks themselves ARE hitting the right page coordinates, but maybe:
  a) The icon doesn't exist in headless/automated browsers
  b) PX detected automation and doesn't show the icon
  c) The icon coords are wrong (we should screenshot to verify)

## Next Steps
1. **Take a screenshot** right before/during the clicks to visually see if the icon exists
2. **Check the nested iframe** — the "Human verification challenge" iframe might have the actual content
3. If no icon visible → focus on making press-and-hold work with CDP
4. Consider: PX may intentionally hide accessibility features for detected bots

## Press-and-Hold Status
- Currently attempting 17s hold via CDP
- Need to check if that's finishing and what result it gives
