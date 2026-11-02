"""Publication/export plots using Matplotlib, from the actual held-out metrics."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.metrics import ConfusionMatrixDisplay


def export(directory):
    directory=Path(directory)
    metrics=json.loads((directory/'metrics.json').read_text())
    for metric in ['accuracy','loss']:
        fig,ax=plt.subplots(figsize=(7,4),layout='constrained')
        for name,title,color in [(metric,'Training','#087f74'),('val_'+metric,'Validation','#bd712e')]:
            ax.plot([r['epoch'] for r in metrics['history']],[r[name] for r in metrics['history']],label=title,color=color)
        ax.set(xlabel='Epoch',ylabel=metric.title(),title='Thermal CNN: '+metric.title())
        ax.grid(alpha=.2)
        ax.legend()
        for ext in ['svg','png']:
            fig.savefig(directory/(metric+'.'+ext),dpi=180)
        plt.close(fig)
    import numpy as np
    fig,ax=plt.subplots(figsize=(7,6),layout='constrained')
    ConfusionMatrixDisplay(np.array(metrics['confusion_matrix']),display_labels=metrics['labels']).plot(ax=ax,cmap='GnBu',colorbar=False)
    ax.set_title('Held-out thermal emotion confusion matrix')
    for ext in ['svg','png']:
        fig.savefig(directory/('confusion.'+ext),dpi=180)
    plt.close(fig)


if __name__=='__main__':
    export(Path(__file__).resolve().parent/'artifacts')
