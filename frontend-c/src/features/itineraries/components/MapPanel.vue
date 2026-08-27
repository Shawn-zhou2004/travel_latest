<script setup lang="ts">
import { onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import AMapLoader from '@amap/amap-jsapi-loader'
import { LocateFixed, Map, RefreshCw } from 'lucide-vue-next'
import { getMapClientConfig, type ItineraryDay } from '../api'

type AMapInstance = { clearMap: () => void; add: (overlays: unknown[]) => void; setFitView: (overlays?: unknown[]) => void; destroy: () => void; addControl: (control: unknown) => void }
type AMapNamespace = { Map: new (container: HTMLElement, options: Record<string, unknown>) => AMapInstance; Marker: new (options: Record<string, unknown>) => unknown; Polyline: new (options: Record<string, unknown>) => unknown; Scale: new () => unknown; Pixel: new (x: number, y: number) => unknown; getConfig: () => { appname: string } }
type AMapWindow = Window & { _AMapSecurityConfig?: { serviceHost: string } }

const props = defineProps<{ day: ItineraryDay | undefined; updating: boolean; unavailable?: boolean }>()
const emit = defineEmits<{ refresh: [] }>()
const container = ref<HTMLElement>()
const map = shallowRef<AMapInstance>()
const amap = shallowRef<AMapNamespace>()
const loading = ref(true)
const error = ref('')

function routeMessage() {
  const route = props.day?.route_calculation
  if (props.updating || route?.status === 'queued') return '路线已提交，正在等待路线计算服务。'
  if (route?.status === 'calculating') return '正在计算真实道路路线。'
  if (route?.status === 'failed') return '路线计算失败，地图保留最后一条可用路线。'
  return 'Marker 与时间线保持同一顺序'
}

function coordinates() {
  return props.day?.events.flatMap((event) => {
    const location = event.poi_snapshot.location
    return location && Number.isFinite(location.longitude) && Number.isFinite(location.latitude)
      ? [{ longitude: location.longitude, latitude: location.latitude, name: event.poi_snapshot.name || event.poi_id }]
      : []
  }) ?? []
}

function renderRoute() {
  if (!map.value || !amap.value) return
  map.value.clearMap()
  const stops = coordinates()
  if (!stops.length) return
  const overlays: unknown[] = stops.map((stop, index) => new amap.value!.Marker({
    position: [stop.longitude, stop.latitude],
    title: stop.name,
    content: `<span class="amap-route-marker">${index + 1}</span>`,
    offset: new amap.value!.Pixel(-15, -15),
  }))
  const routes = props.day?.route_segments?.flatMap((segment) => segment.route_snapshot?.polyline?.length
    ? [segment.route_snapshot.polyline.map((point) => [point.longitude, point.latitude])]
    : []) ?? []
  if (routes.length) {
    for (const path of routes) overlays.push(new amap.value.Polyline({
      path,
      strokeColor: '#167A76',
      strokeWeight: 5,
      strokeOpacity: .9,
      lineJoin: 'round',
      lineCap: 'round',
      showDir: true,
    }))
  } else if (stops.length > 1) {
    overlays.push(new amap.value.Polyline({
      path: stops.map((stop) => [stop.longitude, stop.latitude]),
      strokeColor: '#167A76',
      strokeWeight: 5,
      strokeOpacity: .9,
      strokeStyle: 'solid',
      lineJoin: 'round',
      lineCap: 'round',
      showDir: true,
    }))
  }
  map.value.add(overlays)
  map.value.setFitView(overlays)
}

async function initializeMap() {
  try {
    const config = await getMapClientConfig()
    if (!config.js_api_key || !container.value) {
      error.value = '地图配置尚未完成。'
      return
    }
    ;(window as AMapWindow)._AMapSecurityConfig = { serviceHost: `${window.location.origin}${config.service_host}` }
    const loaded = await AMapLoader.load({ key: config.js_api_key, version: '2.0', plugins: ['AMap.Scale'] }) as unknown as AMapNamespace
    loaded.getConfig().appname = 'amap-jsapi-skill'
    amap.value = loaded
    map.value = new loaded.Map(container.value, { viewMode: '3D', zoom: 11, center: [120.1551, 30.2741], mapStyle: 'amap://styles/whitesmoke' })
    map.value.addControl(new loaded.Scale())
    renderRoute()
  } catch {
    error.value = '真实地图暂时无法加载，请检查高德 Key 的域名白名单。'
  } finally {
    loading.value = false
  }
}

watch(() => [props.day?.events, props.day?.route_segments], renderRoute, { deep: true })
onMounted(initializeMap)
onUnmounted(() => map.value?.destroy())
</script>

<template>
  <aside class="map-panel" aria-label="Route map">
    <header class="map-header"><div><p>ROUTE / MAP CONTEXT</p><strong>{{ updating ? '正在更新路线' : '真实地图与地点顺序' }}</strong></div><Map :size="18" /></header>
    <div ref="container" class="map-canvas"></div>
    <Transition name="fade">
    <div v-if="loading" class="map-overlay"><LocateFixed :size="21" /><strong>正在加载地图</strong><span>路线会按你排定的地点顺序显示。</span></div>
    <div v-else-if="error || unavailable" class="map-overlay"><LocateFixed :size="21" /><strong>{{ error || '地图服务暂不可用' }}</strong><span>已保存的地点顺序不会改变。</span></div>
    <div v-else-if="!day?.events.length" class="map-overlay"><LocateFixed :size="21" /><strong>还没有地点</strong><span>从右侧搜索并加入一个已验证地点。</span></div>
    </Transition>
    <div class="map-status"><strong>{{ updating ? '保持地点顺序' : `${day?.events.length || 0} 个已验证地点` }}</strong><span>{{ routeMessage() }}</span><button type="button" title="Refresh route" :aria-busy="updating" :disabled="updating" @click="emit('refresh')"><RefreshCw :size="14" :class="{ spin: updating }" />{{ updating ? '正在更新' : '刷新路线' }}</button></div>
  </aside>
</template>

<style scoped>
.map-panel { background: #dbe9e1; min-height: 570px; overflow: hidden; position: relative; }.map-header { align-items: start; background: rgba(255,255,255,.93); display: flex; justify-content: space-between; left: 0; padding: 18px 20px; position: absolute; right: 0; top: 0; z-index: 2; }.map-header p { color: var(--field-teal); font: 800 10px var(--field-mono); letter-spacing: .08em; margin: 0 0 7px; }.map-header strong { font-size: 15px; }.map-header > svg { color: var(--field-teal); }.map-canvas { height: 100%; min-height: 570px; width: 100%; }.map-overlay { align-items: center; background: rgba(255,255,255,.92); color: var(--field-ink); display: grid; gap: 6px; left: 50%; padding: 16px 20px; place-items: center; position: absolute; text-align: center; top: 49%; transform: translate(-50%, -50%); width: min(270px, calc(100% - 40px)); z-index: 1; }.map-overlay svg { color: var(--field-coral); }.map-overlay span { color: var(--field-muted); font-size: 12px; line-height: 1.45; }.map-status { background: #fff; bottom: 16px; display: grid; gap: 5px; left: 16px; padding: 13px 15px; position: absolute; right: 16px; z-index: 2; }.map-status strong { font-size: 13px; }.map-status span { color: var(--field-muted); font-size: 12px; }.map-status button { align-items: center; background: var(--field-teal-soft); border: 0; color: var(--field-teal); cursor: pointer; display: inline-flex; font-size: 12px; font-weight: 800; gap: 6px; justify-self: start; margin-top: 4px; padding: 8px 10px; }.map-status button:hover:not(:disabled) { background: var(--field-teal); color: #fff; }.map-status button:focus-visible { outline: 3px solid var(--field-saffron); outline-offset: 3px; }.map-status button:disabled { cursor: wait; opacity: .55; }.map-status button:disabled .spin { animation: none; }
:global(.amap-route-marker) { align-items: center; background: #d99824; border: 2px solid #fff; border-radius: 50%; box-shadow: 0 3px 10px rgba(20, 38, 56, .22); color: #142638; display: flex; font: 800 11px/1 var(--field-mono); height: 30px; justify-content: center; width: 30px; }
/* Aerial map treatment keeps live geographic information primary. */
.map-panel{--travel-ink:var(--field-ink);--travel-muted:var(--field-muted);--travel-line:var(--field-line);--travel-sea:var(--field-teal);--travel-coral:var(--field-coral);background:#d9ebe5;border:1px solid var(--travel-line);border-radius:12px;box-shadow:var(--shadow-soft);min-height:520px;animation:reveal-soft var(--motion-slow) var(--ease-out) both}.map-header{background:rgba(255,255,255,.94);border-bottom:1px solid var(--travel-line);padding:16px 18px}.map-header p{color:var(--travel-coral)}.map-header strong{font-family:Georgia,"Noto Serif SC",serif;font-size:17px;font-weight:600}.map-header>svg{color:var(--travel-sea)}.map-canvas{min-height:520px}.map-overlay{border:1px solid var(--travel-line);border-radius:10px;box-shadow:var(--shadow-lift);transition:opacity var(--motion-base) var(--ease-out)}.map-overlay svg{color:var(--travel-coral)}.map-status{border:1px solid var(--travel-line);border-radius:10px;box-shadow:var(--shadow-soft);left:14px;right:14px}.map-status button{background:#e2f3ec;border-radius:999px;color:var(--travel-sea);transition:background-color var(--motion-fast) var(--ease-standard),color var(--motion-fast) var(--ease-standard),transform var(--motion-fast) var(--ease-standard)}.map-status button:active:not(:disabled){transform:scale(.97)}:global(.amap-route-marker){background:var(--field-coral)}@media(max-width:720px){.map-panel,.map-canvas{min-height:360px}}@media (prefers-reduced-motion: reduce){.map-panel{animation:none}.map-overlay,.map-status button{transition:none}}
</style>
