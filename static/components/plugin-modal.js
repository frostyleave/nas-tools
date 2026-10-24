(function () {
  'use strict';

  function fixedText(value) {
    return (!value || value === 'None' || value === 'null' || value === 'undefined') ? '' : value;
  }

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // 用于拼接 javascript:xxx('id') 里的字符串参数
  function jsString(value) {
    return String(value == null ? '' : value)
      .replace(/\\/g, '\\\\')
      .replace(/'/g, "\\'")
      .replace(/\r/g, '\\r')
      .replace(/\n/g, '\\n')
      .replace(/</g, '\\x3c');
  }

  function parseJSON(value, fallback) {
    if (!value) return fallback;
    try {
      return JSON.parse(value);
    } catch (e) {
      console.warn('[plugin-modal] JSON 解析失败:', e);
      return fallback;
    }
  }

  function renderNote(tooltip) {
    return tooltip
      ? `<span class="form-help" data-bs-toggle="tooltip" title="${esc(tooltip)}">?</span>`
      : '';
  }

  function renderText(field, config, prefix) {
    const required = field.required ? ' ' + esc(field.required) : '';
    const note = renderNote(field.tooltip);
    const hidden = field.hidden ? 'none' : 'block';
    const type = field.type === 'password' ? 'password' : 'text';
    const content = Array.isArray(field.content) ? field.content : [];

    const body = content.map((item, index) => {
      const value = config[item.id] || item.default || '';
      const input = `<input type="${index === 0 ? type : 'text'}" value="${esc(value)}"
        class="form-control" id="${esc(prefix + item.id)}"
        placeholder="${esc(item.placeholder || '')}" autocomplete="off">`;
      if (index === 0) {
        return `<div class="mb-1">
          <label class="form-label${required}">${esc(field.title || '')} ${note}</label>
          ${input}
        </div>`;
      }
      return `<div class="mb-3">${input}</div>`;
    }).join('');

    return `<div class="col-12 col-lg" style="display:${hidden}">${body}</div>`;
  }

  function renderSwitch(field, config, prefix) {
    const required = field.required ? ' ' + esc(field.required) : '';
    const checked = config[field.id] ||
      (config[field.id] === undefined && field.default);
    const onclick = field.onclick ? ` onclick="${esc(field.onclick)}"` : '';

    return `<div class="col-12 col-lg" style="display:${field.hidden ? 'none' : 'block'}">
      <div class="mb-1">
        <label class="form-check form-switch${required}">
          <input class="form-check-input" type="checkbox"
            id="${esc(prefix + field.id)}"${onclick}${checked ? ' checked' : ''}>
          <span class="form-check-label">${esc(field.title || '')} ${renderNote(field.tooltip)}</span>
        </label>
      </div>
    </div>`;
  }

  function renderSelect(field, config, prefix) {
    const required = field.required ? ' ' + esc(field.required) : '';
    const note = renderNote(field.tooltip);
    const content = Array.isArray(field.content) ? field.content : [];

    const body = content.map((item) => {
      const current = config[item.id];
      const options = Object.keys(item.options || {}).map((value) => {
        const selected = current
          ? String(current) === String(value)
          : (item.default != null && String(item.default) === String(value));
        return `<option value="${esc(value)}"${selected ? ' selected' : ''}>${esc(item.options[value])}</option>`;
      }).join('');
      const onchange = item.onchange ? ` onchange="${esc(item.onchange)}"` : '';

      return `<div class="mb-1">
        <label class="form-label${required}">${esc(field.title || '')} ${note}</label>
        <select class="form-control" id="${esc(prefix + item.id)}"${onchange}>${options}</select>
      </div>`;
    }).join('');

    return `<div class="col-12 col-lg" style="display:${field.hidden ? 'none' : 'block'}">${body}</div>`;
  }

  function renderTextarea(field, config, prefix) {
    const content = field.content || {};
    const required = field.required ? ' ' + esc(field.required) : '';
    const id = content.id;
    const rows = Number(content.rows) || 5;
    const label = field.title
      ? `<label class="form-label${required}">${esc(field.title)} ${renderNote(field.tooltip)}</label>`
      : '';
    const readonly = field.readonly ? ' readonly' : '';

    return `<div class="col-12 col-lg" style="display:${field.hidden ? 'none' : 'block'}">
      <div class="mb-1">
        ${label}
        <textarea class="form-control" id="${esc(prefix + id)}" rows="${rows}"
          placeholder="${esc(content.placeholder || '')}"${readonly}>${esc(config[id] || '')}</textarea>
      </div>
    </div>`;
  }

  function renderFormSelectgroup(field, config, prefix) {
    const inputType = field.radio ? 'radio' : 'checkbox';
    const onclick = field.onclick ? ` onclick="${esc(field.onclick)}"` : '';
    const current = config[field.id];
    const content = field.content || {};

    const body = Object.keys(content).map((value) => {
      let checked = false;
      if (Array.isArray(current)) {
        checked = current.includes(value);
      } else if (typeof current === 'string') {
        checked = current === value;
      }
      return `<label class="form-selectgroup-item">
        <input type="${inputType}" name="${esc(prefix + field.id)}" value="${esc(value)}"
          ${onclick} class="form-selectgroup-input"${checked ? ' checked' : ''}>
        <span class="form-selectgroup-label">${esc(content[value].name)}</span>
      </label>`;
    }).join('');

    return `<div class="col-12 col-lg">
      <div class="mb-1">
        <div class="form-selectgroup" id="${esc(prefix + field.id)}" data-type="${inputType}">
          ${body}
        </div>
      </div>
    </div>`;
  }

  function renderDiv(field, config, prefix) {
    const rows = Array.isArray(field.content) ? field.content : [];
    return rows.map((row) => {
      const cols = (Array.isArray(row) ? row : []).map((col) => {
        switch (col.type) {
          case 'text':
          case 'password': return renderText(col, config, prefix);
          case 'switch': return renderSwitch(col, config, prefix);
          case 'select': return renderSelect(col, config, prefix);
          case 'textarea': return renderTextarea(col, config, prefix);
          case 'form-selectgroup': return renderFormSelectgroup(col, config, prefix);
          default: return '';
        }
      }).join('');
      return `<div class="row mb-2">${cols}</div>`;
    }).join('');
  }

  function renderDetails(field, config, prefix) {
    return `<details class="mb-2" id="${esc(prefix + (field.id || ''))}"
      style="display:${field.hidden ? 'none' : 'block'}"${field.open ? ' open' : ''}>
      <summary class="summary mb-2">
        ${esc(field.summary || '')} ${renderNote(field.tooltip)}
      </summary>
      ${renderDiv(field, config, prefix)}
    </details>`;
  }

  function renderFields(fields, config, prefix) {
    return (Array.isArray(fields) ? fields : []).map((field) => {
      switch (field.type) {
        case 'div': return renderDiv(field, config, prefix);
        case 'details': return renderDetails(field, config, prefix);
        default: return '';
      }
    }).join('');
  }

  function renderModal(id, name, config, fields, prefix, page) {
    const idArg = jsString(id);
    const prefixArg = jsString(prefix);
    const extraHref = esc(`javascript:show_plugin_extra_page('${idArg}')`);
    const saveHref = esc(`javascript:save_plugin_config('${idArg}', '${prefixArg}')`);

    return `<div class="modal modal-blur fade" id="modal-plugin-${esc(id)}"
        tabindex="-1" role="dialog" aria-hidden="true"
        data-bs-backdrop="static" data-bs-keyboard="false">
      <div class="modal-dialog modal-lg modal-dialog-centered" role="document">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">${esc(name)}</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body" style="overflow-y: auto">
            ${renderFields(fields, config, prefix)}
          </div>
          <div class="modal-footer">
            <a href="${extraHref}" class="btn me-auto"${page ? '' : ' hidden'}>${esc(page)}</a>
            <a href="${saveHref}" class="btn btn-primary">确定</a>
          </div>
        </div>
      </div>
    </div>`;
  }

  class PluginModal extends HTMLElement {
    connectedCallback() {
      if (this._rendered) return;
      this._rendered = true;

      const id = fixedText(this.getAttribute('plugin-id'));
      const name = fixedText(this.getAttribute('plugin-name'));
      const config = parseJSON(this.getAttribute('plugin-config'), {});
      const fields = parseJSON(this.getAttribute('plugin-fields'), []);
      const prefix = fixedText(this.getAttribute('plugin-prefix'));
      const page = fixedText(this.getAttribute('plugin-page'));

      this.innerHTML = renderModal(id, name, config, fields, prefix, page);

      // 插件脚本在 modal 之后才 append，延后执行初始化
      const runInit = () => {
        const fn = window[id + '_PluginInit'];
        if (typeof fn === 'function') fn();
      };
      if (typeof queueMicrotask === 'function') {
        queueMicrotask(runInit);
      } else {
        setTimeout(runInit, 0);
      }
    }
  }

  if (!customElements.get('plugin-modal')) {
    customElements.define('plugin-modal', PluginModal);
  }
})();
