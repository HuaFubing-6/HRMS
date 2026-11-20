"""
表单统一样式基类（utils 五件套之一）
====================================

作用：给 ModelForm / Form 的所有字段自动加 Bootstrap 样式和 placeholder，
这样模板里只要 {{ field }} 渲染，样式就是统一的，
不用在每个模板里手工写 class="form-control"。

为什么单独抽成基类，而不是每个表单里写一遍 __init__？
—— 全站十几个表单，样式规则只有一份，改一次全站生效。

与教学模板的差异：模板里的判断是
    if field.widget.attrs:  → 设置 class
    else:                   → 也设置 class
两个分支的结果相同，属于冗余写法，这里改成 setdefault 直给。
另外加了"勾选框不加 form-control"的判断 —— 复选框/单选框加了
form-control 会被 Bootstrap 当成文本输入框撑成方块，页面会变形。
"""
from django import forms


class BootStrap:
    """公共基类：循环给所有字段套 Bootstrap 样式"""

    # 这些 widget 不吃 form-control，保持原生外观
    SKIP_WIDGETS = (
        forms.CheckboxInput,
        forms.CheckboxSelectMultiple,
        forms.RadioSelect,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, self.SKIP_WIDGETS):
                continue
            # setdefault：字段自己指定过 class（比如自定义 widget）就尊重它，不覆盖
            field.widget.attrs.setdefault("class", "form-control")
            if field.label and "placeholder" not in field.widget.attrs:
                field.widget.attrs["placeholder"] = field.label


class BootStrapModelForm(BootStrap, forms.ModelForm):
    """给 ModelForm 用（项目里的业务表单都是这种）"""
    pass


class BootStrapForm(BootStrap, forms.Form):
    """给普通 Form 用（比如登录表单）"""
    pass
