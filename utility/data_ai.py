import pandas as pd
import matplotlib.pyplot as plt
import io
import os

# Global settings
verbose = False  # Override default setting with `pandas_gpt.verbose = True`
mutable = False  # Override default setting with `pandas_gpt.mutable = True`

model = 'gpt-3.5-turbo'
completion_config = {}

template = '''
Write a Python function `process({arg_name})` which takes the following input value:

{arg_name} = {arg}

This is the function's purpose: {goal}
'''

_ask_cache = {}


class Ask:
    def __init__(self, *, verbose=None, mutable=None):
        self.verbose = verbose if verbose is not None else globals()['verbose']
        self.mutable = mutable if mutable is not None else globals()['mutable']

    @staticmethod
    def _fill_template(template, **kw):
        import re
        from textwrap import dedent
        result = dedent(template.lstrip('\n').rstrip())
        for k, v in kw.items():
            result = result.replace(f'{{{k}}}', v)
        m = re.match(r'\{[a-zA-Z0-9_]*\}', result)
        if m:
            raise Exception(f'Expected variable: {m.group(0)}')
        return result

    def _get_prompt(self, goal, arg):
        if isinstance(arg, pd.DataFrame) or isinstance(arg, pd.Series):
            import io
            buf = io.StringIO()
            arg.info(buf=buf)
            arg_summary = buf.getvalue()
        else:
            arg_summary = repr(arg)
        arg_name = 'df' if isinstance(arg, pd.DataFrame) else 'index' if isinstance(arg, pd.Index) else 'data'

        return self._fill_template(template, arg_name=arg_name, arg=arg_summary.strip(), goal=goal.strip())

    def _run_prompt(self, prompt):
        import openai
        cache = _ask_cache
        completion = cache.get(prompt) or openai.ChatCompletion.create(
            model=model,
            messages=[
                dict(role='system',
                     content='Write the function in a Python code block with all necessary imports and no example usage.'),
                dict(role='user', content=prompt),
            ],
            **completion_config,
        )
        cache[prompt] = completion
        return completion.choices[0].message.content

    def _extract_code_block(self, text):
        import re
        pattern = r'```(\s*(py|python)\s*\n)?([\s\S]*?)```'
        m = re.search(pattern, text)
        if not m:
            return text
        return m.group(3)

    def _eval(self, source, *args):
        _args_ = args
        scope = dict(_args_=args)
        exec(self._fill_template('''
            {source}
            _result_ = process(*_args_)
        ''', source=source), scope)
        return scope['_result_']

    def _code(self, goal, arg):
        prompt = self._get_prompt(goal, arg)
        result = self._run_prompt(prompt)
        if self.verbose:
            print()
            print(result)
        return self._extract_code_block(result)

    def code(self, *args):
        print(self._code(*args))

    def prompt(self, *args):
        print(self._get_prompt(*args))

    def __call__(self, goal, *args):
        source = self._code(goal, *args)
        return self._eval(source, *args)


class AskPlot(Ask):
    def __init__(self, *, verbose=None, mutable=None):
        super().__init__(verbose=verbose, mutable=mutable)

    def _get_prompt(self, goal, arg):
        # Modify prompt specifically for generating plots
        goal += " Generate a plot with a figure size of (30, 12). Rotate the x-axis labels by 20 degrees. Do not use a tight layout. Save the plot as an image file named 'output'."
        return super()._get_prompt(goal, arg)

    def _save_plot(self, code, data):
        scope = {'df': data}  # Pass the data as 'df' to the process function
        exec(code, scope)
        # Assuming the generated code defines a function `process` which creates a plot
        scope['process'](scope['df'])
        plt.close()  # Close the plot to free memory


    def __call__(self, goal, *args):
        source = self._code(goal, *args)
        data = args[0]  # Get the data (df or Series) from args
        self._save_plot(source, data)
        # Return the file path to the user
        return os.getcwd() + '/output.png'


@pd.api.extensions.register_dataframe_accessor('ask')
@pd.api.extensions.register_series_accessor('ask')
@pd.api.extensions.register_index_accessor('ask')
class AskAccessor:
    def __init__(self, pandas_obj):
        self._validate(pandas_obj)
        self._obj = pandas_obj

    @staticmethod
    def _validate(obj):
        pass

    def _ask(self, **kw):
        return Ask(**kw)

    def _ask_plot(self, **kw):
        return AskPlot(**kw)

    def _data(self, **kw):
        if not mutable and not kw.get('mutable') and hasattr(self._obj, 'copy'):
            return self._obj.copy()  # TODO: possibly `deep=False`
        return self._obj

    def __call__(self, goal, *args, **kw):
        ask = self._ask(**kw)
        data = self._data(**kw)
        return ask(goal, data, *args)

    def code(self, goal, *args, **kw):
        ask = self._ask(**kw)
        data = self._data(**kw)
        return ask.code(goal, data, *args)

    def prompt(self, goal, *args, **kw):
        ask = self._ask(**kw)
        data = self._data(**kw)
        return ask.prompt(goal, data, *args)

    def plot(self, goal, *args, file_path='output_plot.png', **kw):
        ask_plot = self._ask_plot(**kw)
        data = self._data(**kw)
        return ask_plot(goal, data)
