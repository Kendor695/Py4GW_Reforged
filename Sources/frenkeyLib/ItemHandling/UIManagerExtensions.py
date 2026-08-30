import Py4GW
import PyUIManager

from Py4GWCoreLib.Inventory import Inventory
from Py4GWCoreLib.UIManager import UIManager
from Sources.frenkeyLib.ItemHandling.Rules.types import SalvageMode
from Py4GWCoreLib.FrameTree import Frame, FrameId


class UIManagerExtensions:
    @staticmethod
    def _frame_exists(frame: Frame | None) -> bool:
        return frame is not None and frame.is_usable

    @staticmethod
    def IsElementVisible(frame: Frame | None) -> bool:
        """
        Check if a specific frame is open in the UI.

        Args:
            frame_id (int): The ID of the frame to check.

        Returns:
            bool: True if the frame is open, False otherwise.
        """
        return UIManagerExtensions._frame_exists(frame)

    @staticmethod
    def _find_first_visible_frame(frames: list[Frame]) -> Frame | None:
        for frame in frames:
            if UIManagerExtensions._frame_exists(frame):
                return frame
        return None

    @staticmethod
    def _click_frame(frame: Frame | None) -> bool:
        if frame is None or not UIManagerExtensions._frame_exists(frame):
            return False

        frame.click()
        frame.mouse_action(8, 0, 0)
        return True

    @staticmethod
    def _get_confirm_salvage_window_frame_id() -> Frame | None:
        for candidate in (
            Frame(FrameId.ScreenFrame.C6.LesserSalvageWindow.SalvageWithLesserKitConfirm),
            Frame(FrameId.ScreenFrame.C6.SalvageMaterialsDialog.YesButton),
            Frame(FrameId.SalvageWindow.OptionsWindowConfirmMaterialsWindow.Confirm),
        ):
            if candidate.exists:
                return candidate
        return None

    @staticmethod
    def _get_salvage_option_entries():
        try:
            visible_entries_by_parent = Inventory._build_visible_frame_entry_map()
            _, _, option_entries = Inventory._get_salvage_choice_dialog_options(visible_entries_by_parent)
            return option_entries
        except Exception:
            return []
    
    @staticmethod
    def GetSalvageOptions() -> dict[SalvageMode, Frame]:
        options: dict[SalvageMode, Frame] = {}

        # These mode-specific aliases are the established salvage UI contract: Option1 is
        # Prefix, Option2 is Suffix, Option3 is Inscription, and Option4 is Materials.
        # Do not collapse all upgrade modes into the first visible row. A live dialog can
        # contain both an insignia and a rune, where doing so extracts the wrong component.
        prefix_option = Frame(FrameId.SalvageWindow.Options.Option1)
        suffix_option = Frame(FrameId.SalvageWindow.Options.Option2)
        inscription_option = Frame(FrameId.SalvageWindow.Options.Option3)
        materials_option = Frame(FrameId.SalvageWindow.Options.Option4)

        if prefix_option.exists:
            options[SalvageMode.Prefix] = prefix_option

        if suffix_option.exists:
            options[SalvageMode.Suffix] = suffix_option

        if inscription_option.exists:
            options[SalvageMode.Inscription] = inscription_option

        if materials_option.exists:
            options[SalvageMode.LesserCraftingMaterials] = materials_option
            options[SalvageMode.RareCraftingMaterials] = materials_option

        return options
    
    @staticmethod
    def ConfirmSalvageOption() -> bool:
        button = Frame(FrameId.SalvageWindow.Button)
        frame = Inventory._salvage_confirm()
        if not frame.exists:
            if not button.exists:
                return False
            frame = button

        return UIManagerExtensions._click_frame(frame)
    
    @staticmethod
    def CancelSalvageOption() -> bool:
        salvage_window_cancel_button_id = Frame(FrameId.SalvageWindow.CancelButton)
        if not salvage_window_cancel_button_id.exists:
            return False

        return UIManagerExtensions._click_frame(salvage_window_cancel_button_id)
    
    @staticmethod
    def SelectSalvageOptionAndSalvage(option: SalvageMode) -> bool:
        """
        Select a salvage option in the salvage window.

        Args:
            option (SalvageMode): The salvage option to select.

        Returns:
            bool: True if the option was successfully selected, False otherwise.
        """
        options = UIManagerExtensions.GetSalvageOptions()

        if option in options:
            if UIManagerExtensions._click_frame(options[option]):
                return UIManagerExtensions.ConfirmSalvageOption()
        else:
            UIManagerExtensions.CancelSalvageOption()

        return False
    
    @staticmethod
    def SelectSalvageOption(option: SalvageMode) -> bool:
        """
        Select a salvage option in the salvage window.

        Args:
            option (SalvageMode): The salvage option to select.

        Returns:
            bool: True if the option was successfully selected, False otherwise.
        """
        options = UIManagerExtensions.GetSalvageOptions()

        if option in options:
            return UIManagerExtensions._click_frame(options[option])

        return False
    
    @staticmethod
    def IsUpgradeWindowOpen() -> bool:
        upgrade_window_frame_id = Frame(FrameId.UpgradeWindow)
        return upgrade_window_frame_id.exists
    
    @staticmethod
    def IsMerchantWindowOpen() -> bool:
        merchant_window_frame_id = Frame(FrameId.Merchant)
        # merchant_window_frame_inner_id = Frame.from_hash(3613855137, [ # 0])
        # merchant_window_funds_id = Frame(FrameId.GoldText)
        # merchant_window_buy_button_id = Frame(FrameId.MerchantBuyButton)

        return merchant_window_frame_id.exists
        
    @staticmethod
    def IsCollectorOpen() -> bool:        
        merchant_buy_button = 1532320307
        crafter_craft_button = 1517397806
        exchange_collector_button = Frame(FrameId.Merchant.C0.C0.Exchange)
        sell_tab = Frame(FrameId.Merchant.C0.QuoteField)

        return exchange_collector_button.exists and not sell_tab.exists
    
    @staticmethod
    def IsSkillTrainerOpen() -> bool:     
        display_type_button_id = Frame(FrameId.SkillTrainerWindow.DisplayModeButton)
        sell_tab = Frame(FrameId.Merchant.C0.QuoteField)

        return display_type_button_id.exists and not sell_tab.exists
    
    @staticmethod
    def IsCrafterOpen() -> bool:
        crafter_craft_button_id = Frame(FrameId.CraftButton)

        return crafter_craft_button_id.exists

    @staticmethod
    def IsConfirmLesserMaterialsWindowOpen() -> bool:
        return Inventory.IsSalvageChoiceMaterialConfirmVisible() or UIManagerExtensions._get_confirm_salvage_window_frame_id() is not None

    @staticmethod
    def ConfirmLesserSalvage():
        inventory = Inventory.inventory_instance()
        try:
            inventory.AcceptSalvageWindow()
        except Exception:
            pass
        return UIManagerExtensions._click_frame(UIManagerExtensions._get_confirm_salvage_window_frame_id())

    @staticmethod
    def ConfirmModMaterialSalvage():
        inventory = Inventory.inventory_instance()
        try:
            inventory.AcceptSalvageWindow()
        except Exception:
            pass
        return UIManagerExtensions._click_frame(UIManagerExtensions._get_confirm_salvage_window_frame_id())
        
    @staticmethod
    def ConfirmModMaterialSalvageVisible():
        return Inventory.IsSalvageChoiceMaterialConfirmVisible() or UIManagerExtensions._get_confirm_salvage_window_frame_id() is not None
        
    @staticmethod
    def CancelLesserSalvage():
        salvage_lower_kit_no_button_id = Frame.from_hash(140452905, [ 6, 100, 4])
        salvage_lower_kit_no_button_id.click()
    
    @staticmethod
    def IsSalvageWindowOpen() -> bool:
        return Frame(FrameId.SalvageWindow.Button).exists
    
    @staticmethod
    def IsSalvageWindowNoIdentifiedOpen() -> bool:
        salvage_window_salvage_button_id = Frame(FrameId.ScreenFrame.C6.LesserSalvageWindow.SalvageWithLesserKitConfirm)
        return salvage_window_salvage_button_id.exists
    
    @staticmethod
    def ConfirmSalvageWindowNoIdentified():
        inventory = Inventory.inventory_instance()
        try:
            inventory.AcceptSalvageWindow()
        except Exception:
            pass
        return UIManagerExtensions._click_frame(
            Frame(FrameId.ScreenFrame.C6.LesserSalvageWindow.SalvageWithLesserKitConfirm)
        )
            
    
    @staticmethod
    def AnySalvageRelatedWindowOpen() -> bool:
        return (
            UIManagerExtensions.IsSalvageWindowOpen()
            or UIManagerExtensions.IsConfirmLesserMaterialsWindowOpen()
            or UIManagerExtensions.ConfirmModMaterialSalvageVisible()
            or UIManagerExtensions.IsSalvageWindowNoIdentifiedOpen()
        )
