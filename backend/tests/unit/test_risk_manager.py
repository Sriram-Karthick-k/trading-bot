"""
Tests for RiskManager.
"""


from app.core.risk_manager import RiskManager, RiskLimits
from app.providers.types import (
    Exchange, OrderType, ProductType, TransactionType, OrderRequest,
)


def _order(symbol="RELIANCE", exchange=Exchange.NSE, qty=10, product=ProductType.CNC):
    return OrderRequest(
        exchange=exchange,
        tradingsymbol=symbol,
        transaction_type=TransactionType.BUY,
        order_type=OrderType.MARKET,
        quantity=qty,
        product=product,
    )


class TestRiskManager:
    def test_passes_valid_order(self, risk_manager, sample_order_request):
        result = risk_manager.check_order(sample_order_request, price=2500.0)
        assert result.passed is True

    def test_rejects_when_kill_switch_active(self, risk_manager, sample_order_request):
        risk_manager.activate_kill_switch()
        result = risk_manager.check_order(sample_order_request, price=2500.0)
        assert result.passed is False
        assert result.rule == "kill_switch"

    def test_rejects_excessive_order_value(self, risk_manager):
        result = risk_manager.check_order(_order(qty=1000), price=1000.0)
        assert result.passed is False
        assert result.rule == "max_order_value"

    def test_rejects_excessive_quantity(self, risk_manager):
        result = risk_manager.check_order(_order(qty=10000), price=10.0)
        assert result.passed is False
        assert result.rule == "max_quantity"

    def test_rejects_when_too_many_open_orders(self, risk_manager, sample_order_request):
        result = risk_manager.check_order(sample_order_request, price=2500.0, open_orders=20)
        assert result.passed is False
        assert result.rule == "max_open_orders"

    def test_rejects_when_too_many_positions(self, risk_manager, sample_order_request):
        result = risk_manager.check_order(sample_order_request, price=2500.0, open_positions=10)
        assert result.passed is False
        assert result.rule == "max_open_positions"

    def test_daily_loss_tracking(self, risk_manager, sample_order_request):
        risk_manager.record_trade_pnl(-25000)
        risk_manager.record_trade_pnl(-26000)
        result = risk_manager.check_order(sample_order_request, price=2500.0)
        assert result.passed is False
        assert result.rule == "max_daily_loss"

    def test_daily_pnl_report(self, risk_manager):
        risk_manager.record_trade_pnl(5000)
        risk_manager.record_trade_pnl(-3000)
        assert risk_manager.get_daily_pnl() == 2000.0

    def test_kill_switch_toggle(self, risk_manager):
        risk_manager.activate_kill_switch()
        assert risk_manager.limits.kill_switch_active is True
        risk_manager.deactivate_kill_switch()
        assert risk_manager.limits.kill_switch_active is False

    def test_get_status(self, risk_manager):
        status = risk_manager.get_status()
        assert "kill_switch_active" in status
        assert "daily_pnl" in status

    def test_disallowed_exchange(self):
        rm = RiskManager(limits=RiskLimits(allowed_exchanges=["NSE"]))
        result = rm.check_order(
            _order(symbol="CRUDEOIL", exchange=Exchange.MCX, qty=1, product=ProductType.MIS),
            price=5000.0,
        )
        assert result.passed is False
        assert result.rule == "exchange_filter"
