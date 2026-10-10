// 擴充 Wagtail 內建的 TableInput：把後台拖拉的欄寬（px）存進 value.colWidths，
// 前台再用 <colgroup> 一比一輸出（見 ResizableTableBlock）。
//
// Wagtail 的 table.js 每次儲存都會用 JSON 覆寫 hidden input，且不包含欄寬，
// 所以這裡攔截該 input 的 value setter，在每次寫入時補上目前的欄寬。
(function () {
  const BaseTableInput =
    window.telepath.constructors['wagtail.widgets.TableInput'];
  const valueDescriptor = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    'value',
  );
  const pendingIds = new Set();

  function getColWidths(hot) {
    const widths = [];
    for (let col = 0; col < hot.countCols(); col += 1) {
      widths.push(Math.round(hot.getColWidth(col)));
    }
    return widths;
  }

  function attach(hot, input) {
    Object.defineProperty(input, 'value', {
      configurable: true,
      get() {
        return valueDescriptor.get.call(input);
      },
      set(raw) {
        let value = raw;
        try {
          const data = JSON.parse(raw);
          if (data && typeof data === 'object') {
            data.colWidths = getColWidths(hot);
            value = JSON.stringify(data);
          }
        } catch (e) {
          // 非 JSON 就原樣寫入
        }
        valueDescriptor.set.call(input, value);
      },
    });

    // 拖拉欄寬、增刪欄後重新寫一次，讓 setter 補上最新欄寬
    const resave = () => {
      input.value = valueDescriptor.get.call(input);
    };
    hot.addHook('afterColumnResize', resave);
    hot.addHook('afterCreateCol', resave);
    hot.addHook('afterRemoveCol', resave);
    resave();
  }

  window.Handsontable.hooks.add('afterInit', function () {
    const container = this.rootElement;
    if (!container || !container.id) return;
    const inputId = container.id.replace(/-handsontable-container$/, '');
    if (!pendingIds.has(inputId)) return;
    const input = document.getElementById(inputId);
    if (input) attach(this, input);
  });

  class ResizableTableInput extends BaseTableInput {
    render(placeholder, name, id, initialState) {
      const savedWidths = initialState && initialState.colWidths;
      const originalOptions = this.options;
      if (Array.isArray(savedWidths) && savedWidths.length) {
        this.options = { ...originalOptions, manualColumnResize: savedWidths };
      }
      pendingIds.add(id);
      try {
        const widget = super.render(placeholder, name, id, initialState);
        const emptyOption = document.querySelector(
          `#${CSS.escape(id)}-table-header-choice option[value=""]`,
        );
        if (emptyOption) emptyOption.textContent = '請選擇標題格設定';
        return widget;
      } finally {
        this.options = originalOptions;
      }
    }
  }

  window.telepath.register(
    'myproject.widgets.ResizableTableInput',
    ResizableTableInput,
  );
})();
