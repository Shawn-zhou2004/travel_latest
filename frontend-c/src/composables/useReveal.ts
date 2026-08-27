import { onBeforeUnmount, onMounted, type Ref } from 'vue'

/**
 * 滚动触发入场动画 composable。
 *
 * 用法：在页面根元素上挂 `ref`，给需要滚动入场的子元素加 `data-reveal` 属性
 * （可用 `--reveal-index` 自定义错峰）。元素进入视口时添加 `.is-revealed`，
 * 触发 tokens.css 中定义的 opacity + translateY 过渡，仅触发一次。
 *
 * 无障碍：`prefers-reduced-motion` 下 CSS 会直接显示元素，composable 仍会标记
 * `.is-revealed` 以保证内容可见，不会产生位移。
 *
 * 测试环境（jsdom 无 IntersectionObserver）下立即全部标记可见，保证用例稳定。
 */
export function useReveal(root: Ref<HTMLElement | null | undefined>, options: { threshold?: number; rootMargin?: string } = {}) {
  const { threshold = 0.12, rootMargin = '0px 0px -8% 0px' } = options
  let observer: IntersectionObserver | undefined
  let mutationObserver: MutationObserver | undefined
  const watched = new WeakSet<Element>()

  function observe(node: Element) {
    if (!observer || watched.has(node)) return
    watched.add(node)
    observer.observe(node)
  }

  function scan(container: ParentNode) {
    container.querySelectorAll<HTMLElement>('[data-reveal]').forEach(observe)
  }

  function revealAll() {
    const el = root.value
    if (!el) return
    el.querySelectorAll<HTMLElement>('[data-reveal]').forEach((node) => node.classList.add('is-revealed'))
  }

  onMounted(() => {
    const el = root.value
    if (!el) return
    if (typeof IntersectionObserver === 'undefined') {
      revealAll()
      return
    }
    observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-revealed')
            observer?.unobserve(entry.target)
          }
        }
      },
      { threshold, rootMargin },
    )
    scan(el)
    // 动态渲染的 [data-reveal]（如 v-if/v-else 切换后才出现的元素）会错过 onMounted 时的扫描，
    // 这里监听子树变化，自动 observe 后续新增节点，避免它们永远停留在 opacity:0。
    if (typeof MutationObserver !== 'undefined') {
      mutationObserver = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
          mutation.addedNodes.forEach((node) => {
            if (node.nodeType !== Node.ELEMENT_NODE) return
            const element = node as Element
            if (typeof element.matches === 'function' && element.matches('[data-reveal]')) observe(element)
            scan(element)
          })
        }
      })
      mutationObserver.observe(el, { childList: true, subtree: true })
    }
  })

  onBeforeUnmount(() => {
    observer?.disconnect()
    observer = undefined
    mutationObserver?.disconnect()
    mutationObserver = undefined
  })

  return { revealAll }
}
