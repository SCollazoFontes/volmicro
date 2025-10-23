class Strategy:
    def __init__(self, data, params=None):
        self.data = data
        self.params = params or {}

    def generate_signals(self):
        """
        Método que debe implementar cada estrategia.
        Debe devolver una serie pandas con señales (1=compra, -1=venta, 0=mantener)
        """
        raise NotImplementedError("Cada estrategia debe implementar generate_signals().")