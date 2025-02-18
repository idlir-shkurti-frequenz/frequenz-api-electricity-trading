# License: MIT
# Copyright © 2023 Frequenz Energy-as-a-Service GmbH

"""Module to define the client class."""

from datetime import datetime
from typing import Awaitable, cast

import grpc
from frequenz.api.electricity_trading.v1 import (
    electricity_trading_pb2,
    electricity_trading_pb2_grpc,
)
from frequenz.channels import Receiver
from frequenz.client.base.grpc_streaming_helper import GrpcStreamingHelper
from google.protobuf import field_mask_pb2, struct_pb2

from ._types import (
    DeliveryArea,
    DeliveryPeriod,
    Energy,
    GridpoolOrderFilter,
    GridpoolTradeFilter,
    MarketSide,
    Order,
    OrderDetail,
    OrderExecutionOption,
    OrderState,
    OrderType,
    PaginationParams,
    Price,
    PublicTrade,
    PublicTradeFilter,
    Trade,
    TradeState,
    UpdateOrder,
)


class _Sentinel:
    """A unique object to signify 'no value passed'."""


NO_VALUE = _Sentinel()


class Client:
    """Electricity trading client."""

    def __init__(self, grpc_channel: grpc.aio.Channel) -> None:
        """Initialize the client.

        Args:
            grpc_channel: gRPC channel to use for communication with the API.
        """
        self._stub = electricity_trading_pb2_grpc.ElectricityTradingServiceStub(
            grpc_channel
        )

        self._gridpool_orders_streams: dict[
            tuple[int, GridpoolOrderFilter],
            GrpcStreamingHelper[
                electricity_trading_pb2.ReceiveGridpoolOrdersStreamResponse, OrderDetail
            ],
        ] = {}

        self._gridpool_trades_streams: dict[
            tuple[int, GridpoolTradeFilter],
            GrpcStreamingHelper[
                electricity_trading_pb2.ReceiveGridpoolTradesStreamResponse, Trade
            ],
        ] = {}

        self._public_trades_streams: dict[
            PublicTradeFilter,
            GrpcStreamingHelper[
                electricity_trading_pb2.ReceivePublicTradesStreamResponse, PublicTrade
            ],
        ] = {}

    async def stream_gridpool_orders(  # pylint: disable=too-many-arguments
        self,
        gridpool_id: int,
        order_states: list[OrderState] | None = None,
        market_side: MarketSide | None = None,
        delivery_area: DeliveryArea | None = None,
        delivery_period: DeliveryPeriod | None = None,
        tag: str | None = None,
    ) -> Receiver[OrderDetail]:
        """
        Stream gridpool orders.

        Args:
            gridpool_id: ID of the gridpool to stream orders for.
            order_states: List of order states to filter for.
            market_side: Market side to filter for.
            delivery_area: Delivery area to filter for.
            delivery_period: Delivery period to filter for.
            tag: Tag to filter for.

        Returns:
            Async generator of orders.
        """
        gridpool_order_filter = GridpoolOrderFilter(
            order_states=order_states,
            side=market_side,
            delivery_area=delivery_area,
            delivery_period=delivery_period,
            tag=tag,
        )

        stream_key = (gridpool_id, gridpool_order_filter)

        if stream_key not in self._gridpool_orders_streams:
            self._gridpool_orders_streams[stream_key] = GrpcStreamingHelper(
                f"electricity-trading-{stream_key}",
                lambda: self._stub.ReceiveGridpoolOrdersStream(  # type: ignore
                    electricity_trading_pb2.ReceiveGridpoolOrdersStreamRequest(
                        gridpool_id=gridpool_id,
                        filter=gridpool_order_filter.to_pb(),
                    )
                ),
                lambda response: OrderDetail.from_pb(response.order_detail),
            )
        return self._gridpool_orders_streams[stream_key].new_receiver()

    async def stream_gridpool_trades(  # pylint: disable=too-many-arguments
        self,
        gridpool_id: int,
        trade_states: list[TradeState] | None = None,
        trade_ids: list[int] | None = None,
        market_side: MarketSide | None = None,
        delivery_period: DeliveryPeriod | None = None,
        delivery_area: DeliveryArea | None = None,
    ) -> Receiver[Trade]:
        """
        Stream gridpool trades.

        Args:
            gridpool_id: The ID of the gridpool to stream trades for.
            trade_states: List of trade states to filter for.
            trade_ids: List of trade IDs to filter for.
            market_side: The market side to filter for.
            delivery_period: The delivery period to filter for.
            delivery_area: The delivery area to filter for.

        Returns:
            The gridpool trades streamer.
        """
        gridpool_trade_filter = GridpoolTradeFilter(
            trade_states=trade_states,
            trade_id_lists=trade_ids,
            side=market_side,
            delivery_period=delivery_period,
            delivery_area=delivery_area,
        )

        stream_key = (gridpool_id, gridpool_trade_filter)

        if stream_key not in self._gridpool_trades_streams:
            self._gridpool_trades_streams[stream_key] = GrpcStreamingHelper(
                f"electricity-trading-{gridpool_trade_filter}",
                lambda: self._stub.ReceiveGridpoolTradesStream(  # type: ignore
                    electricity_trading_pb2.ReceiveGridpoolTradesStreamRequest(
                        gridpool_id=gridpool_id,
                        filter=gridpool_trade_filter.to_pb(),
                    )
                ),
                lambda response: Trade.from_pb(response.trade),
            )
        return self._gridpool_trades_streams[stream_key].new_receiver()

    async def stream_public_trades(
        self,
        states: list[TradeState] | None = None,
        delivery_period: DeliveryPeriod | None = None,
        buy_delivery_area: DeliveryArea | None = None,
        sell_delivery_area: DeliveryArea | None = None,
    ) -> Receiver[PublicTrade]:
        """
        Stream public trades.

        Args:
            states: List of order states to filter for.
            delivery_period: Delivery period to filter for.
            buy_delivery_area: Buy delivery area to filter for.
            sell_delivery_area: Sell delivery area to filter for.

        Returns:
            Async generator of orders.
        """
        public_trade_filter = PublicTradeFilter(
            states=states,
            delivery_period=delivery_period,
            buy_delivery_area=buy_delivery_area,
            sell_delivery_area=sell_delivery_area,
        )

        if public_trade_filter not in self._public_trades_streams:
            self._public_trades_streams[public_trade_filter] = GrpcStreamingHelper(
                f"electricity-trading-{public_trade_filter}",
                lambda: self._stub.ReceivePublicTradesStream(  # type: ignore
                    electricity_trading_pb2.ReceivePublicTradesStreamRequest(
                        filter=public_trade_filter.to_pb(),
                    )
                ),
                lambda response: PublicTrade.from_pb(response.public_trade),
            )
        return self._public_trades_streams[public_trade_filter].new_receiver()

    async def create_gridpool_order(  # pylint: disable=too-many-arguments, too-many-locals
        self,
        gridpool_id: int,
        delivery_area: DeliveryArea,
        delivery_period: DeliveryPeriod,
        order_type: OrderType,
        side: MarketSide,
        price: Price,
        quantity: Energy,
        stop_price: Price | None = None,
        peak_price_delta: Price | None = None,
        display_quantity: Energy | None = None,
        execution_option: OrderExecutionOption | None = None,
        valid_until: datetime | None = None,
        payload: dict[str, struct_pb2.Value] | None = None,
        tag: str | None = None,
    ) -> OrderDetail:
        """
        Create a gridpool order.

        Args:
            gridpool_id: ID of the gridpool to create the order for.
            delivery_area: Delivery area of the order.
            delivery_period: Delivery period of the order.
            order_type: Type of the order.
            side: Side of the order.
            price: Price of the order.
            quantity: Quantity of the order.
            stop_price: Stop price of the order.
            peak_price_delta: Peak price delta of the order.
            display_quantity: Display quantity of the order.
            execution_option: Execution option of the order.
            valid_until: Valid until of the order.
            payload: Payload of the order.
            tag: Tag of the order.

        Returns:
            The created order.
        """
        order = Order(
            delivery_area=delivery_area,
            delivery_period=delivery_period,
            type=order_type,
            side=side,
            price=price,
            quantity=quantity,
            stop_price=stop_price,
            peak_price_delta=peak_price_delta,
            display_quantity=display_quantity,
            execution_option=execution_option,
            valid_until=valid_until,
            payload=payload,
            tag=tag,
        )

        response = await cast(
            Awaitable[electricity_trading_pb2.CreateGridpoolOrderResponse],
            self._stub.CreateGridpoolOrder(
                electricity_trading_pb2.CreateGridpoolOrderRequest(
                    gridpool_id=gridpool_id,
                    order=order.to_pb(),
                )
            ),
        )

        return OrderDetail.from_pb(response.order_detail)

    async def update_gridpool_order(  # pylint: disable=too-many-arguments, too-many-locals
        self,
        gridpool_id: int,
        order_id: int,
        price: Price | None | _Sentinel = NO_VALUE,
        quantity: Energy | None | _Sentinel = NO_VALUE,
        stop_price: Price | None | _Sentinel = NO_VALUE,
        peak_price_delta: Price | None | _Sentinel = NO_VALUE,
        display_quantity: Energy | None | _Sentinel = NO_VALUE,
        execution_option: OrderExecutionOption | None | _Sentinel = NO_VALUE,
        valid_until: datetime | None | _Sentinel = NO_VALUE,
        payload: dict[str, struct_pb2.Value] | None | _Sentinel = NO_VALUE,
        tag: str | None | _Sentinel = NO_VALUE,
    ) -> OrderDetail:
        """
        Update an existing order for a given Gridpool.

        Args:
            gridpool_id: ID of the Gridpool the order belongs to.
            order_id: Order ID.
            price: The updated limit price at which the contract is to be traded.
                This is the maximum price for a BUY order or the minimum price for a SELL order.
            quantity: The updated quantity of the contract being traded, specified in MWh.
            stop_price: Applicable for STOP_LIMIT orders. This is the updated stop price that
                triggers the limit order.
            peak_price_delta: Applicable for ICEBERG orders. This is the updated price difference
                between the peak price and the limit price.
            display_quantity: Applicable for ICEBERG orders. This is the updated quantity of the
                order to be displayed in the order book.
            execution_option: Updated execution options such as All or None, Fill or Kill, etc.
            valid_until: This is an updated timestamp defining the time after which the order
                should be cancelled if not filled. The timestamp is in UTC.
            payload: Updated user-defined payload individual to a specific order. This can be any
                data that the user wants to associate with the order.
            tag: Updated user-defined tag to group related orders.

        Returns:
            The updated order.

        Raises:
            ValueError: If no fields to update are provided.
        """
        params = {
            "price": price,
            "quantity": quantity,
            "stop_price": stop_price,
            "peak_price_delta": peak_price_delta,
            "display_quantity": display_quantity,
            "execution_option": execution_option,
            "valid_until": valid_until,
            "payload": payload,
            "tag": tag,
        }

        if all(value is NO_VALUE for value in params.values()):
            raise ValueError("At least one field to update must be provided.")

        paths = [param for param, value in params.items() if value is not NO_VALUE]

        # Field mask specifying which fields should be updated
        # This is used so that we can update parameters with None values
        update_mask = field_mask_pb2.FieldMask(paths=paths)

        update_order_fields = UpdateOrder(
            price=None if price is NO_VALUE else price,
            quantity=None if quantity is NO_VALUE else quantity,
            stop_price=None if stop_price is NO_VALUE else stop_price,
            peak_price_delta=None if peak_price_delta is NO_VALUE else peak_price_delta,
            display_quantity=None if display_quantity is NO_VALUE else display_quantity,
            execution_option=None if execution_option is NO_VALUE else execution_option,
            valid_until=None if valid_until is NO_VALUE else valid_until,
            payload=None if payload is NO_VALUE else payload,
            tag=None if tag is NO_VALUE else tag,
        )

        response = await cast(
            Awaitable[electricity_trading_pb2.UpdateGridpoolOrderResponse],
            self._stub.UpdateGridpoolOrder(
                electricity_trading_pb2.UpdateGridpoolOrderRequest(
                    gridpool_id=gridpool_id,
                    order_id=order_id,
                    update_order_fields=update_order_fields.to_pb(),
                    update_mask=update_mask,
                )
            ),
        )

        return OrderDetail.from_pb(response.order_detail)

    async def cancel_gridpool_order(
        self, gridpool_id: int, order_id: int
    ) -> OrderDetail:
        """
        Cancel a single order for a given Gridpool.

        Args:
            gridpool_id: The Gridpool to cancel the order for.
            order_id: The order to cancel.

        Returns:
            The cancelled order.
        """
        response = await cast(
            Awaitable[electricity_trading_pb2.CancelGridpoolOrderResponse],
            self._stub.CancelGridpoolOrder(
                electricity_trading_pb2.CancelGridpoolOrderRequest(
                    gridpool_id=gridpool_id, order_id=order_id
                )
            ),
        )

        return OrderDetail.from_pb(response.order_detail)

    async def cancel_all_gridpool_orders(self, gridpool_id: int) -> int:
        """
        Cancel all orders for a specific Gridpool.

        Args:
            gridpool_id: The Gridpool to cancel the orders for.

        Returns:
            The ID of the Gridpool for which the orders were cancelled.
        """
        response = await cast(
            Awaitable[electricity_trading_pb2.CancelAllGridpoolOrdersResponse],
            self._stub.CancelAllGridpoolOrders(
                electricity_trading_pb2.CancelAllGridpoolOrdersRequest(
                    gridpool_id=gridpool_id
                )
            ),
        )

        return response.gridpool_id

    async def get_gridpool_order(self, gridpool_id: int, order_id: int) -> OrderDetail:
        """
        Get a single order from a given gridpool.

        Args:
            gridpool_id: The Gridpool to retrieve the order for.
            order_id: The order to retrieve.

        Returns:
            The order.
        """
        response = await cast(
            Awaitable[electricity_trading_pb2.GetGridpoolOrderResponse],
            self._stub.GetGridpoolOrder(
                electricity_trading_pb2.GetGridpoolOrderRequest(
                    gridpool_id=gridpool_id, order_id=order_id
                )
            ),
        )

        return OrderDetail.from_pb(response.order_detail)

    async def list_gridpool_orders(  # pylint: disable=too-many-arguments
        self,
        gridpool_id: int,
        order_states: list[OrderState] | None = None,
        side: MarketSide | None = None,
        delivery_period: DeliveryPeriod | None = None,
        delivery_area: DeliveryArea | None = None,
        tag: str | None = None,
        max_nr_orders: int | None = None,
        page_token: str | None = None,
    ) -> list[OrderDetail]:
        """
        List orders for a specific Gridpool with optional filters.

        Args:
            gridpool_id: The Gridpool to retrieve the orders for.
            order_states: List of order states to filter by.
            side: The side of the market to filter by.
            delivery_period: The delivery period to filter by.
            delivery_area: The delivery area to filter by.
            tag: The tag to filter by.
            max_nr_orders: The maximum number of orders to return.
            page_token: The page token to use for pagination.

        Returns:
            The list of orders for that gridpool.
        """
        gridpool_order_filer = GridpoolOrderFilter(
            order_states=order_states,
            side=side,
            delivery_period=delivery_period,
            delivery_area=delivery_area,
            tag=tag,
        )

        pagination_params = PaginationParams(
            page_size=max_nr_orders,
            page_token=page_token,
        )

        response = await cast(
            Awaitable[electricity_trading_pb2.ListGridpoolOrdersResponse],
            self._stub.ListGridpoolOrders(
                electricity_trading_pb2.ListGridpoolOrdersRequest(
                    gridpool_id=gridpool_id,
                    filter=gridpool_order_filer.to_pb(),
                    pagination_params=pagination_params.to_pb(),
                )
            ),
        )

        return [
            OrderDetail.from_pb(order_detail)
            for order_detail in response.order_detail_lists
        ]

    async def list_gridpool_trades(  # pylint: disable=too-many-arguments
        self,
        gridpool_id: int,
        trade_states: list[TradeState] | None = None,
        trade_id_lists: list[int] | None = None,
        market_side: MarketSide | None = None,
        delivery_period: DeliveryPeriod | None = None,
        delivery_area: DeliveryArea | None = None,
        max_nr_orders: int | None = None,
        page_token: str | None = None,
    ) -> list[Trade]:
        """
        List trades for a specific Gridpool with optional filters.

        Args:
            gridpool_id: The Gridpool to retrieve the trades for.
            trade_states: List of trade states to filter by.
            trade_id_lists: List of trade IDs to filter by.
            market_side: The side of the market to filter by.
            delivery_period: The delivery period to filter by.
            delivery_area: The delivery area to filter by.
            max_nr_orders: The maximum number of orders to return.
            page_token: The page token to use for pagination.

        Returns:
            The list of trades for the given gridpool.
        """
        gridpool_trade_filter = GridpoolTradeFilter(
            trade_states=trade_states,
            trade_id_lists=trade_id_lists,
            side=market_side,
            delivery_period=delivery_period,
            delivery_area=delivery_area,
        )

        pagination_params = PaginationParams(
            page_size=max_nr_orders,
            page_token=page_token,
        )

        response = await cast(
            Awaitable[electricity_trading_pb2.ListGridpoolTradesResponse],
            self._stub.ListGridpoolTrades(
                electricity_trading_pb2.ListGridpoolTradesRequest(
                    gridpool_id=gridpool_id,
                    filter=gridpool_trade_filter.to_pb(),
                    pagination_params=pagination_params.to_pb(),
                )
            ),
        )

        return [Trade.from_pb(trade) for trade in response.trade_lists]

    async def list_public_trades(  # pylint: disable=too-many-arguments
        self,
        states: list[OrderState] | None = None,
        delivery_period: DeliveryPeriod | None = None,
        buy_delivery_area: DeliveryArea | None = None,
        sell_delivery_area: DeliveryArea | None = None,
        max_nr_orders: int | None = None,
        page_token: str | None = None,
    ) -> list[PublicTrade]:
        """
        List all executed public orders with optional filters.

        Args:
            states: List of order states to filter by.
            delivery_period: The delivery period to filter by.
            buy_delivery_area: The buy delivery area to filter by.
            sell_delivery_area: The sell delivery area to filter by.
            max_nr_orders: The maximum number of orders to return.
            page_token: The page token to use for pagination.

        Returns:
            The list of public trades.
        """
        public_trade_filter = PublicTradeFilter(
            states=states,
            delivery_period=delivery_period,
            buy_delivery_area=buy_delivery_area,
            sell_delivery_area=sell_delivery_area,
        )

        pagination_params = PaginationParams(
            page_size=max_nr_orders,
            page_token=page_token,
        )

        response = await cast(
            Awaitable[electricity_trading_pb2.ListPublicTradesResponse],
            self._stub.ListPublicTrades(
                electricity_trading_pb2.ListPublicTradesRequest(
                    filter=public_trade_filter.to_pb(),
                    pagination_params=pagination_params.to_pb(),
                )
            ),
        )

        return [
            PublicTrade.from_pb(public_trade)
            for public_trade in response.public_trade_lists
        ]
