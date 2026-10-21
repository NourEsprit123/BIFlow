SCROLL_JS = """
<script>
try {
  const doc = window.parent.document;
  const box = doc.querySelector('.st-key-bf_chat_msgs');
  if (box) {
    const nodes = [box, ...box.querySelectorAll('div')];
    const scroller = nodes.find(e => e.scrollHeight > e.clientHeight + 5);
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  }
} catch (e) {}
</script>
"""