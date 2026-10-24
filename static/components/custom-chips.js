(function () {
  'use strict';

  const TITLES = {
    rev_string: '识别用名',
    ignored_words: '应用屏蔽词',
    replaced_words: '应用替换词',
    offset_words: '应用集数偏移',
    type: '类型',
    category: '类别',
    name: '识别名称',
    title: '标题',
    tmdbid: 'TMDB ID',
    year: '年份',
    season_episode: '季集',
    part: '分集',
    restype: '质量',
    effect: '特性',
    pix: '分辨率',
    video_codec: '视频编码',
    audio_codec: '音频编码',
    team: '制作组/字幕组',
    customization: '自定义占位符'
  };

  function colorFor(type, content) {
    switch (type) {
      case 'rev_string':
        return 'badge-outline text-wrap text-orange mt-2';
      case 'ignored_words':
      case 'replaced_words':
      case 'offset_words':
        return 'badge-outline text-wrap text-cyan';
      case 'type':
      case 'category':
        return 'bg-blue';
      case 'name':
        return content === '无法识别' ? 'bg-red text-wrap' : 'bg-yellow text-wrap';
      case 'title':
        return content !== '未匹配TMDB' ? 'bg-green' : 'bg-red';
      case 'tmdbid':
        return 'bg-green';
      case 'year':
      case 'season_episode':
      case 'part':
        return 'bg-orange';
      case 'team':
        return 'bg-cyan text-wrap';
      default:
        return '';
    }
  }

  function asText(value) {
    return value == null ? '' : String(value);
  }

  class CustomChips extends HTMLElement {
    connectedCallback() {
      if (!this.hasChildNodes()) {
        this.render(
          this.getArgs('data-type'),
          this.getArgs('data-text'),
          this.getArgs('data-href')
        );
      }
    }

    add_chips_all(sortArray, data) {
      // 组件自己负责清空，调用方不需要再 .empty()
      this.replaceChildren();

      const customWordsFlag = (data.ignored_words ? data.ignored_words.length : 0)
        + (data.replaced_words ? data.replaced_words.length : 0)
        + (data.offset_words ? data.offset_words.length : 0);

      (sortArray || []).forEach((key) => {
        let href = '';
        let flag = null;
        let content = data[key];

        switch (key) {
          case 'name':
            href = data.name === '无法识别'
              ? null
              : `https://www.themoviedb.org/search?query=${encodeURIComponent(data.name || '')}`;
            break;
          case 'tmdbid':
            href = data.tmdblink;
            break;
          case 'season_episode':
            href = data.tmdb_S_E_link;
            break;
          case 'org_string':
          case 'ignored_words':
          case 'replaced_words':
          case 'offset_words':
            flag = customWordsFlag;
            break;
          case 'title':
            content = !data.tmdbid ? '未匹配TMDB' : data.title;
            href = data.tmdblink;
            break;
        }

        this.render(key, content, href, flag);
        this.style.display = 'block';
      });
    }

    render(chipsType, chipsContent, chipsHref, chipsFlag) {
      if (!chipsContent || !chipsType ||
          !Object.prototype.hasOwnProperty.call(TITLES, chipsType)) {
        return;
      }

      const title = TITLES[chipsType];
      const color = colorFor(chipsType, chipsContent);

      // 屏蔽词 / 替换词 / 偏移：带标题的一组 badge
      if (chipsContent.length && chipsFlag) {
        const label = document.createElement('label');
        label.className = 'form-label mb-1';
        label.textContent = `${title}：`;

        if (typeof chipsContent === 'string') {
          const badge = document.createElement('span');
          badge.className = `badge me-1 ${color}`;
          badge.textContent = chipsContent;
          label.appendChild(badge);
        } else {
          for (const word of chipsContent) {
            const child = document.createElement(
              chipsType === 'ignored_words' ? 'del' : 'span'
            );
            child.className = `badge me-1 ${color}`;
            child.textContent = asText(word);
            label.appendChild(child);
          }
        }

        this.appendChild(label);
        return;
      }

      // 普通字段
      if (chipsFlag == null) {
        const wrapper = document.createElement('span');
        wrapper.title = title;

        if (chipsHref) {
          const link = document.createElement('a');
          link.className = `badge me-1 mb-1 ${color}`;
          link.href = chipsHref;
          link.target = '_blank';
          link.rel = 'noopener noreferrer';
          link.textContent = asText(chipsContent);
          wrapper.appendChild(link);
        } else {
          wrapper.className = `badge me-1 mb-1 ${color}`;
          wrapper.textContent = asText(chipsContent);
        }

        this.appendChild(wrapper);
      }
    }

    getArgs(name, defaultValue) {
      defaultValue = defaultValue || '';
      const value = this.getAttribute(name);
      if (!value || value === 'None' || value === 'null' || value === 'undefined') {
        return defaultValue;
      }
      return value;
    }
  }

  if (!customElements.get('custom-chips')) {
    customElements.define('custom-chips', CustomChips);
  }
})();
