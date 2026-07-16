/*
 * Skeleton boot stub (classic script, loaded in <head> before anything else).
 *
 * Defines a tiny window.Skeletons that QUEUES fill()/clear() calls made before
 * the ES module runtime (skeleton-runtime.mjs) has loaded. Once the module
 * loads it replaces this stub and flushes the queue. This lets page scripts
 * call Skeletons.fill(...) immediately, without caring about module timing.
 */
(function () {
  if (window.Skeletons && window.Skeletons.__ready) return; // real runtime already in
  if (window.Skeletons && window.Skeletons.__queue) return; // stub already installed
  var queue = [];
  window.Skeletons = {
    __stub: true,
    __ready: false,
    __queue: queue,
    fill: function () { queue.push(['fill', Array.prototype.slice.call(arguments)]); },
    clear: function () { queue.push(['clear', Array.prototype.slice.call(arguments)]); },
  };
})();
