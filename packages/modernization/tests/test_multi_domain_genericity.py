"""AUTOFORGE AI — 18-G MULTI-DOMAIN GENERICITY TEST SUITE.

Adversarially tests that the modernized generator compiles and preserves actual
business logic across 5 completely unrelated business domains:
1. Banking (Account balance, fee, overdraft)
2. Retail (Subtotal, quantity discount, tax, total)
3. Insurance (Claim eligibility, deductible, approval status)
4. Payroll (Hours, 1.5x overtime, tax deduction, net pay)
5. Inventory (Stock decrement, safety threshold, reorder qty)

All business behavior must be compiled purely from the technology-neutral semantic AST,
with ZERO domain-specific hardcoded methods or branch templates.
"""

import tempfile
import unittest
from pathlib import Path

from autoforge_modernization.composition.generator import GenericTargetArtifactGenerator
from autoforge_modernization.composition.planner import GenericTransformationPlanner
from autoforge_modernization.composition.verifier import TargetToolchainVerifier
from autoforge_modernization.semantic.extractors import ProjectSemanticExtractor
from autoforge_modernization.semantic.model import (
    SemanticCondition,
    SemanticDataType,
    SemanticField,
    SemanticModule,
    SemanticOperation,
    SemanticOperationKind,
    SemanticProcedure,
    TechnologyNeutralSemanticModel,
)
from autoforge_modernization.target.specification import TargetSpecification


class MultiDomainGenericityTests(unittest.TestCase):
    """Tests generalized code generation across 5 diverse business domains."""

    def setUp(self):
        self.generator = GenericTargetArtifactGenerator()
        self.planner = GenericTransformationPlanner()
        self.verifier = TargetToolchainVerifier()
        self.target_spec = TargetSpecification.java_spring_boot()

    def _compile_and_verify(self, model: TechnologyNeutralSemanticModel) -> list:
        plan = self.planner.plan(model, self.target_spec)
        artifacts = self.generator.generate(model, plan, self.target_spec, include_project_manifests=True)
        self.assertTrue(any(a.relative_path.endswith(".java") for a in artifacts))
        self.assertTrue(any(a.relative_path == "pom.xml" for a in artifacts))
        
        # Verify via Maven compilation
        build_dir = Path(tempfile.mkdtemp(prefix="autoforge_domain_test_"))
        result = self.verifier.verify_maven(artifacts, self.target_spec, build_directory=build_dir)
        self.assertTrue(result.passed, f"Maven compilation failed:\n{result.output_snippet}")
        return artifacts

    def test_domain_a_banking_overdraft(self):
        """Workload A (Banking): Compute balance, assess fee, detect overdraft."""
        mod = SemanticModule(
            name="BankAccService",
            source_file_path="bank/account.cbl",
            source_technology="COBOL",
            source_sha256="bank-sha-123",
            fields=[
                SemanticField(name="curr-bal", data_type=SemanticDataType.INTEGER),
                SemanticField(name="tran-amt", data_type=SemanticDataType.INTEGER),
                SemanticField(name="overdraft-fee", data_type=SemanticDataType.INTEGER),
                SemanticField(name="is-overdrawn", data_type=SemanticDataType.BOOLEAN),
                SemanticField(name="new-bal", data_type=SemanticDataType.INTEGER),
            ],
            procedures=[
                SemanticProcedure(
                    name="POST-TRANSACTION",
                    operations=[
                        SemanticOperation(
                            kind=SemanticOperationKind.COMPUTATION,
                            description="COMPUTE NEW-BAL = CURR-BAL + TRAN-AMT",
                            target="new-bal",
                            mutated_fields=["new-bal"],
                            referenced_fields=["curr-bal", "tran-amt"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.BRANCH,
                            description="IF NEW-BAL < 0",
                            condition=SemanticCondition(expression="NEW-BAL < 0"),
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.ASSIGNMENT,
                            description="MOVE 35 TO OVERDRAFT-FEE",
                            target="overdraft-fee",
                            mutated_fields=["overdraft-fee"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.ASSIGNMENT,
                            description="MOVE 'TRUE' TO IS-OVERDRAWN",
                            target="is-overdrawn",
                            mutated_fields=["is-overdrawn"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.COMPUTATION,
                            description="COMPUTE NEW-BAL = NEW-BAL - OVERDRAFT-FEE",
                            target="new-bal",
                            mutated_fields=["new-bal"],
                            referenced_fields=["new-bal", "overdraft-fee"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.BRANCH,
                            description="ELSE",
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.ASSIGNMENT,
                            description="MOVE 0 TO OVERDRAFT-FEE",
                            target="overdraft-fee",
                            mutated_fields=["overdraft-fee"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.BRANCH,
                            description="END-IF",
                        ),
                    ],
                )
            ],
        )
        model = TechnologyNeutralSemanticModel(project_id="domain-test", modules={"BankAccService": mod})
        artifacts = self._compile_and_verify(model)
        java_src = next(a.code for a in artifacts if "bankaccservice.java" in a.relative_path.lower())
        self.assertIn("public void postTransaction()", java_src)
        self.assertIn("this.newBal = this.currBal + this.tranAmt;", java_src)
        self.assertIn("if (this.newBal < 0L)", java_src)
        self.assertIn("this.overdraftFee = 35L;", java_src)

    def test_domain_b_retail_order(self):
        """Workload B (Retail): Subtotal, 10% discount if qty >= 10, 8% tax, total."""
        mod = SemanticModule(
            name="RetailOrderService",
            source_file_path="retail/order.cbl",
            source_technology="COBOL",
            source_sha256="retail-sha-456",
            fields=[
                SemanticField(name="unit-price", data_type=SemanticDataType.INTEGER),
                SemanticField(name="qty", data_type=SemanticDataType.INTEGER),
                SemanticField(name="subtotal", data_type=SemanticDataType.INTEGER),
                SemanticField(name="discount", data_type=SemanticDataType.INTEGER),
                SemanticField(name="tax", data_type=SemanticDataType.INTEGER),
                SemanticField(name="order-total", data_type=SemanticDataType.INTEGER),
            ],
            procedures=[
                SemanticProcedure(
                    name="CALCULATE-ORDER",
                    operations=[
                        SemanticOperation(
                            kind=SemanticOperationKind.COMPUTATION,
                            description="COMPUTE SUBTOTAL = UNIT-PRICE * QTY",
                            target="subtotal",
                            mutated_fields=["subtotal"],
                            referenced_fields=["unit-price", "qty"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.BRANCH,
                            description="IF QTY >= 10",
                            condition=SemanticCondition(expression="QTY >= 10"),
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.COMPUTATION,
                            description="COMPUTE DISCOUNT = SUBTOTAL / 10",
                            target="discount",
                            mutated_fields=["discount"],
                            referenced_fields=["subtotal"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.BRANCH,
                            description="ELSE",
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.ASSIGNMENT,
                            description="MOVE 0 TO DISCOUNT",
                            target="discount",
                            mutated_fields=["discount"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.BRANCH,
                            description="END-IF",
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.COMPUTATION,
                            description="COMPUTE TAX = (SUBTOTAL - DISCOUNT) * 8 / 100",
                            target="tax",
                            mutated_fields=["tax"],
                            referenced_fields=["subtotal", "discount"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.COMPUTATION,
                            description="COMPUTE ORDER-TOTAL = SUBTOTAL - DISCOUNT + TAX",
                            target="order-total",
                            mutated_fields=["order-total"],
                            referenced_fields=["subtotal", "discount", "tax"],
                        ),
                    ],
                )
            ],
        )
        model = TechnologyNeutralSemanticModel(project_id="domain-test", modules={"RetailOrderService": mod})
        artifacts = self._compile_and_verify(model)
        java_src = next(a.code for a in artifacts if "retailorderservice.java" in a.relative_path.lower())
        self.assertIn("public void calculateOrder()", java_src)
        self.assertIn("this.subtotal = this.unitPrice * this.qty;", java_src)
        self.assertIn("this.orderTotal = this.subtotal - this.discount + this.tax;", java_src)

    def test_domain_c_insurance_claims(self):
        """Workload C (Insurance): Claim deductible subtraction & policy limit validation."""
        mod = SemanticModule(
            name="InsuranceClaimService",
            source_file_path="ins/claim.cbl",
            source_technology="COBOL",
            source_sha256="ins-sha-789",
            fields=[
                SemanticField(name="claim-amount", data_type=SemanticDataType.INTEGER),
                SemanticField(name="deductible", data_type=SemanticDataType.INTEGER),
                SemanticField(name="coverage-limit", data_type=SemanticDataType.INTEGER),
                SemanticField(name="approved-payout", data_type=SemanticDataType.INTEGER),
                SemanticField(name="claim-status", data_type=SemanticDataType.STRING),
            ],
            procedures=[
                SemanticProcedure(
                    name="PROCESS-CLAIM",
                    operations=[
                        SemanticOperation(
                            kind=SemanticOperationKind.BRANCH,
                            description="IF CLAIM-AMOUNT <= DEDUCTIBLE",
                            condition=SemanticCondition(expression="CLAIM-AMOUNT <= DEDUCTIBLE"),
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.ASSIGNMENT,
                            description="MOVE 0 TO APPROVED-PAYOUT",
                            target="approved-payout",
                            mutated_fields=["approved-payout"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.ASSIGNMENT,
                            description="MOVE 'REJECTED-UNDER-DEDUCTIBLE' TO CLAIM-STATUS",
                            target="claim-status",
                            mutated_fields=["claim-status"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.BRANCH,
                            description="ELSE",
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.COMPUTATION,
                            description="COMPUTE APPROVED-PAYOUT = CLAIM-AMOUNT - DEDUCTIBLE",
                            target="approved-payout",
                            mutated_fields=["approved-payout"],
                            referenced_fields=["claim-amount", "deductible"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.BRANCH,
                            description="IF APPROVED-PAYOUT > COVERAGE-LIMIT",
                            condition=SemanticCondition(expression="APPROVED-PAYOUT > COVERAGE-LIMIT"),
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.ASSIGNMENT,
                            description="MOVE COVERAGE-LIMIT TO APPROVED-PAYOUT",
                            target="approved-payout",
                            mutated_fields=["approved-payout"],
                            referenced_fields=["coverage-limit"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.BRANCH,
                            description="END-IF",
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.ASSIGNMENT,
                            description="MOVE 'APPROVED' TO CLAIM-STATUS",
                            target="claim-status",
                            mutated_fields=["claim-status"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.BRANCH,
                            description="END-IF",
                        ),
                    ],
                )
            ],
        )
        model = TechnologyNeutralSemanticModel(project_id="domain-test", modules={"InsuranceClaimService": mod})
        artifacts = self._compile_and_verify(model)
        java_src = next(a.code for a in artifacts if "insuranceclaimservice.java" in a.relative_path.lower())
        self.assertIn("public void processClaim()", java_src)
        self.assertIn("if (this.claimAmount <= this.deductible)", java_src)
        self.assertIn('this.claimStatus = "REJECTED-UNDER-DEDUCTIBLE";', java_src)

    def test_domain_d_payroll_overtime(self):
        """Workload D (Payroll): Base hours + 1.5x overtime + tax withholding."""
        mod = SemanticModule(
            name="PayrollCalculatorService",
            source_file_path="payroll/calc.cbl",
            source_technology="COBOL",
            source_sha256="pay-sha-101",
            fields=[
                SemanticField(name="hourly-rate", data_type=SemanticDataType.INTEGER),
                SemanticField(name="reg-hours", data_type=SemanticDataType.INTEGER),
                SemanticField(name="ot-hours", data_type=SemanticDataType.INTEGER),
                SemanticField(name="gross-pay", data_type=SemanticDataType.INTEGER),
                SemanticField(name="tax-withholding", data_type=SemanticDataType.INTEGER),
                SemanticField(name="net-pay", data_type=SemanticDataType.INTEGER),
            ],
            procedures=[
                SemanticProcedure(
                    name="COMPUTE-PAY",
                    operations=[
                        SemanticOperation(
                            kind=SemanticOperationKind.COMPUTATION,
                            description="COMPUTE GROSS-PAY = (HOURLY-RATE * REG-HOURS) + (HOURLY-RATE * OT-HOURS * 15 / 10)",
                            target="gross-pay",
                            mutated_fields=["gross-pay"],
                            referenced_fields=["hourly-rate", "reg-hours", "ot-hours"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.COMPUTATION,
                            description="COMPUTE TAX-WITHHOLDING = GROSS-PAY * 20 / 100",
                            target="tax-withholding",
                            mutated_fields=["tax-withholding"],
                            referenced_fields=["gross-pay"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.COMPUTATION,
                            description="COMPUTE NET-PAY = GROSS-PAY - TAX-WITHHOLDING",
                            target="net-pay",
                            mutated_fields=["net-pay"],
                            referenced_fields=["gross-pay", "tax-withholding"],
                        ),
                    ],
                )
            ],
        )
        model = TechnologyNeutralSemanticModel(project_id="domain-test", modules={"PayrollCalculatorService": mod})
        artifacts = self._compile_and_verify(model)
        java_src = next(a.code for a in artifacts if "payrollcalculatorservice.java" in a.relative_path.lower())
        self.assertIn("public void computePay()", java_src)
        self.assertIn("this.netPay = this.grossPay - this.taxWithholding;", java_src)

    def test_domain_e_inventory_reorder(self):
        """Workload E (Inventory): Decrement stock, check safety threshold, calculate reorder qty."""
        mod = SemanticModule(
            name="InventoryStockService",
            source_file_path="inv/stock.cbl",
            source_technology="COBOL",
            source_sha256="inv-sha-202",
            fields=[
                SemanticField(name="stock-on-hand", data_type=SemanticDataType.INTEGER),
                SemanticField(name="qty-demanded", data_type=SemanticDataType.INTEGER),
                SemanticField(name="reorder-point", data_type=SemanticDataType.INTEGER),
                SemanticField(name="reorder-qty", data_type=SemanticDataType.INTEGER),
                SemanticField(name="needs-reorder", data_type=SemanticDataType.BOOLEAN),
            ],
            procedures=[
                SemanticProcedure(
                    name="DISPATCH-STOCK",
                    operations=[
                        SemanticOperation(
                            kind=SemanticOperationKind.COMPUTATION,
                            description="SUBTRACT QTY-DEMANDED FROM STOCK-ON-HAND",
                            target="stock-on-hand",
                            mutated_fields=["stock-on-hand"],
                            referenced_fields=["qty-demanded"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.BRANCH,
                            description="IF STOCK-ON-HAND < REORDER-POINT",
                            condition=SemanticCondition(expression="STOCK-ON-HAND < REORDER-POINT"),
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.ASSIGNMENT,
                            description="MOVE 'TRUE' TO NEEDS-REORDER",
                            target="needs-reorder",
                            mutated_fields=["needs-reorder"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.COMPUTATION,
                            description="COMPUTE REORDER-QTY = (REORDER-POINT * 2) - STOCK-ON-HAND",
                            target="reorder-qty",
                            mutated_fields=["reorder-qty"],
                            referenced_fields=["reorder-point", "stock-on-hand"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.BRANCH,
                            description="ELSE",
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.ASSIGNMENT,
                            description="MOVE 'FALSE' TO NEEDS-REORDER",
                            target="needs-reorder",
                            mutated_fields=["needs-reorder"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.ASSIGNMENT,
                            description="MOVE 0 TO REORDER-QTY",
                            target="reorder-qty",
                            mutated_fields=["reorder-qty"],
                        ),
                        SemanticOperation(
                            kind=SemanticOperationKind.BRANCH,
                            description="END-IF",
                        ),
                    ],
                )
            ],
        )
        model = TechnologyNeutralSemanticModel(project_id="domain-test", modules={"InventoryStockService": mod})
        artifacts = self._compile_and_verify(model)
        java_src = next(a.code for a in artifacts if "inventorystockservice.java" in a.relative_path.lower())
        self.assertIn("public void dispatchStock()", java_src)
        self.assertIn("this.stockOnHand -= this.qtyDemanded;", java_src)
        self.assertIn("if (this.stockOnHand < this.reorderPoint)", java_src)


if __name__ == "__main__":
    unittest.main()
